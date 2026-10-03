import os
import sys
import math
import random
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox
import matplotlib.pyplot as plt

# =========================================================
# PUBLISH-GRADE MINIMALIST PLOTTING
# =========================================================
plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman'],
    'axes.labelsize': 10,
    'axes.titlesize': 11,
    'axes.titleweight': 'bold',
    'axes.linewidth': 0.8,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'legend.frameon': False,
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight'
})

def format_publish_axis(ax):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', color='#d3d3d3', linestyle='--', linewidth=0.5, alpha=0.7)

# =========================================================
# REPRODUCIBILITY SEED
# =========================================================
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

# =========================================================
# PSS/E PATHS
# =========================================================
PSSPY_PATH = r"C:\Program Files\PTI\PSSE36\36.6\PSSPY313"
PSSBIN_PATH = r"C:\Program Files\PTI\PSSE36\36.6\PSSBIN"

sys.path.append(PSSPY_PATH)
sys.path.append(PSSBIN_PATH)
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(PSSBIN_PATH)
    os.add_dll_directory(PSSPY_PATH)
else:
    os.environ["PATH"] = PSSBIN_PATH + ";" + PSSPY_PATH + ";" + os.environ.get("PATH", "")

import psspy
import redirect

# =========================================================
# ALGORITHM PARAMETERS
# =========================================================
V_MIN = 0.95
V_MAX = 1.05

POP_SIZE = 50
MAX_GEN = 50
CX_RATE = 0.95
MUT_RATE = 0.35
ELITISM = 6
TOURNAMENT_K = 5

# =========================================================
# PSS/E CONTROLLER FUNCTIONS
# =========================================================
def initialize_psse():
    redirect.psse2py()
    psspy.psseinit(80000)
    psspy.progress_output(2, "NUL", [0, 0]) 
    psspy.alert_output(2, "NUL", [0, 0])
    psspy.prompt_output(2, "NUL", [0, 0])

def load_case(sav_file):
    return psspy.case(sav_file) == 0

def run_loadflow():
    psspy.fnsl([0, 0, 0, 0, 1, 0, 0, 0])
    return psspy.solved() == 0

def apply_tap_ratio(fbus, tbus, ckt, ratio):
    _i, _f, _s = psspy.getdefaultint(), psspy.getdefaultreal(), psspy.getdefaultchar()
    write_success = False

    try:
        ierr = psspy.two_winding_chng_6(int(fbus), int(tbus), str(ckt), [_i]*16, [float(ratio)] + [_f]*20, [_s, _s])
        if (ierr[0] if isinstance(ierr, tuple) else ierr) == 0: write_success = True
    except Exception:
        try:
            realari24 = [_f]*24
            realari24[3] = float(ratio)
            ierr = psspy.two_winding_chng_4(int(fbus), int(tbus), str(ckt), [_i]*15, realari24, [_s, _s])
            if (ierr[0] if isinstance(ierr, tuple) else ierr) == 0: write_success = True
        except Exception: pass

    if not write_success: return False

    ierr, actual_ratio = psspy.xfrdat(int(fbus), int(tbus), str(ckt), "RATIO")
    return ierr == 0 and abs(actual_ratio - ratio) < 1e-4

# =========================================================
# DATA EXTRACTION
# =========================================================
def get_system_totals():
    p_loss, q_loss = psspy.systot('LOSS')[1].real, psspy.systot('LOSS')[1].imag
    p_gen, q_gen = psspy.systot('GEN')[1].real, psspy.systot('GEN')[1].imag
    p_load, q_load = psspy.systot('LOAD')[1].real, psspy.systot('LOAD')[1].imag
    return p_gen, q_gen, p_load, q_load, p_loss, q_loss, p_gen - p_load - p_loss

def get_bus_voltages():
    _, b_nums = psspy.abusint(-1, 2, ["NUMBER"])
    _, v_pu = psspy.abusreal(-1, 2, ["PU"])
    if not b_nums[0]: return None
    return {b: v for b, v in zip(b_nums[0], v_pu[0])}

def discover_transformers():
    _, f_buses = psspy.atrnint(-1, 1, 1, 2, 1, 'FROMNUMBER')
    _, t_buses = psspy.atrnint(-1, 1, 1, 2, 1, 'TONUMBER')
    _, ids = psspy.atrnchar(-1, 1, 1, 2, 1, 'ID')
    
    valid_tx = []
    if f_buses and len(f_buses[0]) > 0:
        for i, j, ckt in zip(f_buses[0], t_buses[0], ids[0]):
            ckt = ckt.strip()
            _, ratio = psspy.xfrdat(i, j, ckt, 'RATIO')
            _, rmin = psspy.xfrdat(i, j, ckt, 'RMIN')
            _, rmax = psspy.xfrdat(i, j, ckt, 'RMAX')
            _, ntp = psspy.xfrint(i, j, ckt, 'NTPOSN')
            
            if rmax > rmin and ntp > 1:
                step = (rmax - rmin) / (ntp - 1)
                grid = [rmin + k * step for k in range(ntp)]
                base_idx = min(range(len(grid)), key=lambda k: abs(grid[k] - ratio))
                valid_tx.append({"from": i, "to": j, "id": ckt, "ntp": ntp, "grid": grid, "base_idx": base_idx, "base_ratio": ratio})
    return valid_tx

# =========================================================
# FITNESS EVALUATION & GA
# =========================================================
def evaluate_chromosome(chromosome, transformers, sav_file):
    if not load_case(sav_file): return (True, 9999.0, 9999.0)
    for idx, tr in zip(chromosome, transformers):
        if not apply_tap_ratio(tr["from"], tr["to"], tr["id"], tr["grid"][idx]): return (True, 9999.0, 9999.0) 
        
    if not run_loadflow(): return (True, 9999.0, 9999.0) 
    voltages = get_bus_voltages()
    if voltages is None: return (True, 9999.0, 9999.0)
        
    loss_mw = psspy.systot('LOSS')[1].real
    voltage_viol = sum(max(0, V_MIN - v, v - V_MAX) for v in voltages.values())
    is_infeasible = (min(voltages.values()) < V_MIN) or (max(voltages.values()) > V_MAX)
    
    return (is_infeasible, voltage_viol, loss_mw)

def tournament_select(population, scores):
    contenders = random.sample(list(zip(population, scores)), TOURNAMENT_K)
    contenders.sort(key=lambda x: x[1]) 
    return contenders[0][0][:]

def report_change(metric, val_before, val_after):
    diff = val_after - val_before
    pct = abs(diff / val_before) * 100 if val_before != 0 else 0.0
    
    if abs(diff) < 1e-4: trend = "Remained unchanged"
    elif diff < 0: trend = f"Decreased by {pct:.2f}%"
    else: trend = f"Increased by {pct:.2f}%"
        
    print(f"{metric:<28} : Base = {val_before:>10.4f}, Opt = {val_after:>10.4f} ({trend})")

# =========================================================
# MAIN EXECUTION
# =========================================================
def main():
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    sav_file = filedialog.askopenfilename(title="Select SAV File", filetypes=[("SAV files", "*.sav")])
    root.destroy()
    if not sav_file: return

    initialize_psse()
    os.chdir(os.path.dirname(sav_file))
    
    if not load_case(sav_file) or not run_loadflow(): 
        messagebox.showerror("Power Flow Error", "Base case failed to converge.")
        return
        
    b_pgen, b_qgen, b_pload, b_qload, b_ploss, b_qloss, b_presid = get_system_totals()
    base_voltages = get_bus_voltages()
    
    transformers = discover_transformers()
    if not transformers: return
        
    base_ratios = [tr["base_ratio"] for tr in transformers]
    initial_grid_chromosome = [tr["base_idx"] for tr in transformers]
    grid_score = evaluate_chromosome(initial_grid_chromosome, transformers, sav_file)
    
    base_vmin, base_vmax = min(base_voltages.values()), max(base_voltages.values())
    base_voltage_viol = sum(max(0, V_MIN - v, v - V_MAX) for v in base_voltages.values())
    
    population = [[random.randint(0, tr["ntp"] - 1) for tr in transformers] for _ in range(POP_SIZE)]
    population[0] = initial_grid_chromosome[:] 
    
    best_chromosome, best_score = initial_grid_chromosome[:], grid_score
    
    # Tracking for Convergence Curve
    best_effort_loss_history = []
    best_feasible_loss_history = []
    
    print("\n" + "=" * 65)
    print("TRANSFORMER TAP OPTIMIZATION (DISCRETE GA)".center(65))
    print("=" * 65)
    print(f"Transformers Detected : {len(transformers)}")
    print(f"GA Parameters         : Pop={POP_SIZE}, Gen={MAX_GEN}, Mut={MUT_RATE}")
    print("-" * 65)

    for gen in range(MAX_GEN):
        scores = [evaluate_chromosome(ind, transformers, sav_file) for ind in population]
        for ind, score in zip(population, scores):
            if score < best_score:
                best_score, best_chromosome = score, ind[:]
                
        scored_pop = sorted(list(zip(population, scores)), key=lambda x: x[1]) 
        next_pop = [ind[:] for ind, score in scored_pop[:ELITISM]]
        
        best_effort_loss_history.append(best_score[2])
        
        # Find best feasible in current generation history
        best_feasible = next((score for score in [s for _, s in scored_pop] if not score[0]), None)
        if best_feasible and (len(best_feasible_loss_history) == 0 or np.isnan(best_feasible_loss_history[-1]) or best_feasible[2] < best_feasible_loss_history[-1]):
            best_feasible_loss_history.append(best_feasible[2])
        elif len(best_feasible_loss_history) > 0 and not np.isnan(best_feasible_loss_history[-1]):
            best_feasible_loss_history.append(best_feasible_loss_history[-1]) 
        else:
            best_feasible_loss_history.append(np.nan)

        while len(next_pop) < POP_SIZE:
            p1 = tournament_select(population, scores)
            p2 = tournament_select(population, scores)
            
            if random.random() < CX_RATE and len(p1) > 1:
                pt = random.randint(1, len(p1) - 1)
                c1, c2 = p1[:pt] + p2[pt:], p2[:pt] + p1[pt:]
            else:
                c1, c2 = p1[:], p2[:]
            
            for child in (c1, c2):
                if len(next_pop) < POP_SIZE:
                    for i, tr in enumerate(transformers):
                        if random.random() < MUT_RATE:
                            child[i] = max(0, min(tr["ntp"] - 1, child[i] + random.choice([-1, 1])))
                    next_pop.append(child)
        population = next_pop
        
        # Clean Console Output
        if best_score[0]: 
            text = f"Best Violation = {best_score[1]:.4f} pu (Infeasible)"
        else:
            text = f"Best Feasible P_Loss = {best_score[2]:.4f} MW"
        
        sys.stdout.write(f"\rGeneration {gen+1:>3}/{MAX_GEN} | {text}")
        sys.stdout.flush()
    print()

    # FINAL RE-CALCULATION
    if best_score[0]:
        print("\n[WARNING] Strict feasibility not reached. Proceeding with Best Effort Solution...")

    load_case(sav_file)
    for idx, tr in zip(best_chromosome, transformers):
        apply_tap_ratio(tr["from"], tr["to"], tr["id"], tr["grid"][idx])
    run_loadflow()
        
    opt_voltages = get_bus_voltages()
    o_pgen, o_qgen, o_pload, o_qload, o_ploss, o_qloss, o_presid = get_system_totals()
    opt_ratios = [tr["grid"][idx] for idx, tr in zip(best_chromosome, transformers)]
    
    opt_vmin, opt_vmax = min(opt_voltages.values()), max(opt_voltages.values())
    opt_feasible = (opt_vmin >= V_MIN) and (opt_vmax <= V_MAX)
    opt_v_viol = sum(max(0, V_MIN - v, v - V_MAX) for v in opt_voltages.values())

    out_sav = os.path.splitext(sav_file)[0] + "_TAP_OPTIMIZED.sav"
    psspy.save(out_sav)

    # CLEAN ACADEMIC TEXT REPORT
    print("\n\n" + "=" * 65)
    print("SYSTEM OPTIMIZATION SUMMARY".center(65))
    print("=" * 65)
    report_change("Total Generation P (MW)", b_pgen, o_pgen)
    report_change("Total Generation Q (MVAR)", b_qgen, o_qgen)
    report_change("Total Load P (MW)", b_pload, o_pload)
    report_change("Total Load Q (MVAR)", b_qload, o_qload)
    report_change("Active Power Loss (MW)", b_ploss, o_ploss)
    report_change("Reactive Power Loss (MVAR)", b_qloss, o_qloss)
    report_change("Power Balance Residual (MW)", b_presid, o_presid)
    report_change("Minimum Voltage (pu)", base_vmin, opt_vmin)
    report_change("Maximum Voltage (pu)", base_vmax, opt_vmax)
    report_change("Total Voltage Violation (pu)", base_voltage_viol, opt_v_viol)

    print("\nTRANSFORMER TAP ADJUSTMENTS\n")
    for t, b_rat, o_rat in zip(transformers, base_ratios, opt_ratios):
        print(f" -> Transformer {t['from']:>2}-{t['to']:<2} : Base = {b_rat:.4f}, Opt = {o_rat:.4f}")

    # =========================================================
    # INDIVIDUAL BUS VOLTAGES (BEFORE vs AFTER)
    # =========================================================
    bus_keys = sorted(list(base_voltages.keys()))
    print("\n" + "=" * 65)
    print("INDIVIDUAL BUS VOLTAGES (BEFORE vs AFTER)".center(65))
    print("=" * 65)
    for bus in bus_keys:
        print(f" -> Bus {bus:>3} : Before = {base_voltages[bus]:.4f} pu  |  After = {opt_voltages[bus]:.4f} pu")
        
    print("\nFINAL STATUS\n")
    pct_reduced = ((b_ploss - o_ploss) / b_ploss) * 100
    if opt_feasible:
        print("Feasibility : FEASIBLE (Project constraint 0.95 <= Vi <= 1.05 pu strictly met)")
        print(f"Objective   : Active Power Loss decreased by {pct_reduced:.2f}%")
    else:
        print("Feasibility : INFEASIBLE (Grid voltage constraints remain violated)")
        print(f"Best effort : Active power loss reduced by {pct_reduced:.2f}%")
        print(f"Voltage     : Remaining constraint violation = {opt_v_viol:.4f} pu")

    print(f"\nExport      : Network saved -> {os.path.basename(out_sav)}")

    # =========================================================
    # PUBLICATION-GRADE FIGURES
    # =========================================================
    x_indices = np.arange(len(bus_keys))
    width = 0.35
    
    color_bef = '#1f4e79' 
    color_aft = '#b22222' 

    y_min_plot = min(base_vmin, opt_vmin, V_MIN) - 0.02
    y_max_plot = max(base_vmax, opt_vmax, V_MAX) + 0.02

    # Figure 1: Voltage Profile (Bar)
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(x_indices - width/2, [base_voltages[b] for b in bus_keys], width, label='Before Optimization', color=color_bef)
    ax1.bar(x_indices + width/2, [opt_voltages[b] for b in bus_keys], width, label='After Optimization', color=color_aft)
    ax1.axhline(V_MIN, color='black', linestyle=':', linewidth=1.5)
    ax1.axhline(V_MAX, color='black', linestyle=':', linewidth=1.5)
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(bus_keys, rotation=90)
    ax1.set_ylim(y_min_plot, y_max_plot)
    ax1.set_title("System Voltage Magnitude Profile (Bar)")
    ax1.set_ylabel("Voltage (pu)")
    ax1.legend(loc="upper right", ncol=2)
    format_publish_axis(ax1)
    fig1.tight_layout()

    # Figure 2: Voltage Profile (Line)
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    ax2.plot(bus_keys, [base_voltages[b] for b in bus_keys], marker='s', color=color_bef, linestyle='-', linewidth=1.5, markersize=4, label='Before Optimization')
    ax2.plot(bus_keys, [opt_voltages[b] for b in bus_keys], marker='o', color=color_aft, linestyle='-', linewidth=1.5, markersize=4, label='After Optimization')
    ax2.axhline(V_MIN, color='black', linestyle=':', linewidth=1.5)
    ax2.axhline(V_MAX, color='black', linestyle=':', linewidth=1.5)
    ax2.set_title("System Voltage Profile Trajectory (Line)")
    ax2.set_xlabel("Bus Number")
    ax2.set_ylabel("Voltage (pu)")
    ax2.set_xticks(bus_keys)
    ax2.set_xticklabels(bus_keys, rotation=90)
    ax2.legend(loc="lower right")
    format_publish_axis(ax2)
    ax2.grid(True, axis='both', color='#e0e0e0', linestyle='--', linewidth=0.5, alpha=0.7)
    fig2.tight_layout()

    # Figure 3: Tap Ratio (Bar)
    fig3, ax3 = plt.subplots(figsize=(8, 4))
    if transformers:
        x_tap = np.arange(len(transformers))
        ax3.bar(x_tap - width/2, base_ratios, width, label='Before Optimization', color=color_bef)
        ax3.bar(x_tap + width/2, opt_ratios, width, label='After Optimization', color=color_aft)
        ax3.set_xticks(x_tap)
        ax3.set_xticklabels([f"{t['from']}-{t['to']}" for t in transformers], rotation=45)
        ax3.set_title("Discrete Transformer Tap Adjustments (Bar)")
        ax3.set_ylabel("Tap Ratio (pu)")
        ax3.legend(loc="upper right")
        format_publish_axis(ax3)
    fig3.tight_layout()

    # Figure 4: Tap Ratio (Line) - RESTORED
    fig4, ax4 = plt.subplots(figsize=(8, 4))
    if transformers:
        ax4.plot(x_tap, base_ratios, marker='s', color=color_bef, linestyle='-', linewidth=1.5, markersize=5, label='Before Optimization')
        ax4.plot(x_tap, opt_ratios, marker='o', color=color_aft, linestyle='-', linewidth=1.5, markersize=5, label='After Optimization')
        ax4.set_xticks(x_tap)
        ax4.set_xticklabels([f"{t['from']}-{t['to']}" for t in transformers], rotation=45)
        ax4.set_title("Discrete Transformer Tap Adjustments (Line)")
        ax4.set_ylabel("Tap Ratio (pu)")
        ax4.legend(loc="upper right")
        format_publish_axis(ax4)
        ax4.grid(True, axis='both', color='#e0e0e0', linestyle='--', linewidth=0.5, alpha=0.7)
    fig4.tight_layout()

    # Figure 5: GA Convergence Curve
    fig5, ax5 = plt.subplots(figsize=(8, 4))
    generations = np.arange(1, MAX_GEN + 1)
    ax5.plot(generations, best_effort_loss_history, color='#1f4e79', linestyle='--', linewidth=1.5, label='Best Effort Search (Infeasible allowed)')
    
    if not np.isnan(best_feasible_loss_history).all():
        ax5.plot(generations, best_feasible_loss_history, color=color_aft, linestyle='-', linewidth=2.5, label='Best Feasible Solution')
        ax5.set_title("GA Objective Convergence (Active Power Loss)")
    else:
        ax5.set_title("GA Objective Convergence (Warning: No Feasible Solutions Found)")
        ax5.text(0.5, 0.5, 'All Evaluated Solutions Remain Infeasible\n(Showing Best-Effort Trajectory)', transform=ax5.transAxes, ha='center', va='center', alpha=0.6, fontsize=11, color='gray', fontweight='bold')

    ax5.set_xlabel("Generation")
    ax5.set_ylabel("Active Power Loss (MW)")
    ax5.legend(loc="upper right")
    format_publish_axis(ax5)
    fig5.tight_layout()

    # Figure 6: All 3 Power Losses (Bar) - FIXED TEXT OVERLAP
    fig6, ax6 = plt.subplots(figsize=(7, 4.5))
    metrics = ['Active Loss\n(MW)', 'Reactive Loss\n(MVAR)', 'Apparent Loss\n(MVA)']
    b_sloss = math.sqrt(b_ploss**2 + b_qloss**2)
    o_sloss = math.sqrt(o_ploss**2 + o_qloss**2)
    base_vals = [b_ploss, b_qloss, b_sloss]
    opt_vals = [o_ploss, o_qloss, o_sloss]
    x_pos = np.arange(len(metrics))
    
    bars1 = ax6.bar(x_pos - width/2, base_vals, width, label='Before Optimization', color=color_bef)
    bars2 = ax6.bar(x_pos + width/2, opt_vals, width, label='After Optimization', color=color_aft)
    
    ax6.set_xticks(x_pos)
    ax6.set_xticklabels(metrics)
    ax6.set_title("System Power Loss Summary")
    ax6.set_ylabel("Loss Magnitude")
    
    max_val = max(max(base_vals), max(opt_vals))
    for bars in [bars1, bars2]:
        for bar in bars:
            yval = bar.get_height()
            ax6.text(bar.get_x() + bar.get_width()/2, yval + (max_val * 0.02), f'{yval:.2f}', ha='center', va='bottom', fontsize=8.5, fontweight='bold')
    
    # CRITICAL FIX: Increased to 1.35 to give text plenty of headroom
    ax6.set_ylim(0, max_val * 1.35)
    ax6.legend(loc="upper right")
    format_publish_axis(ax6)
    fig6.tight_layout()

    plt.show()

if __name__ == "__main__":
    main()