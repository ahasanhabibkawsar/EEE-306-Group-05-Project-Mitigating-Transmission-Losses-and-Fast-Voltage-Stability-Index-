import os
import sys
import math
import random
import numpy as np
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import matplotlib.pyplot as plt

# PUBLISH-GRADE MINIMALIST PLOTTING
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
# REPRODUCIBILITY
# =========================================================
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

# =========================================================
# PSS/E CONFIGURATION
# =========================================================
PSSPY_PATH = r"C:\Program Files\PTI\PSSE36\36.6\PSSPY313"
PSSBIN_PATH = r"C:\Program Files\PTI\PSSE36\36.6\PSSBIN"

sys.path.append(PSSPY_PATH)
sys.path.append(PSSBIN_PATH)

if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(PSSBIN_PATH)
    os.add_dll_directory(PSSPY_PATH)
else:
    os.environ["PATH"] = (PSSBIN_PATH + ";" + PSSPY_PATH + ";" + os.environ.get("PATH", ""))

import psspy
import redirect

# =========================================================
# PROJECT OPERATING CONSTRAINTS
# =========================================================
V_MIN = 0.95
V_MAX = 1.05
STEP_MVAR = 5.0

# =========================================================
# PSO PARAMETERS 
# =========================================================
C1 = 2.05
C2 = 2.05
PHI = C1 + C2
CHI = 2.0 / abs(2.0 - PHI - math.sqrt(PHI**2 - 4.0 * PHI))
SWARM_SIZE = 60          
MAX_ITER = 60            
VELOCITY_LIMIT_FACTOR = 0.50

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
    ierr = psspy.fnsl([0, 0, 0, 0, 1, 0, 0, 0])
    if ierr != 0: return False
    return psspy.solved() == 0

def apply_shunt_capacitor(bus, mvar):
    """Safely injects a shunt. Auto-increments ID to avoid overwriting existing data."""
    for i in range(1, 100):
        sid = str(i).ljust(2)
        ierr = psspy.shunt_data(int(bus), sid, [1], [0.0, float(mvar)])
        if ierr == 0:  
            return True
        elif ierr == 2: 
            continue
    return False

# =========================================================
# SYSTEM DATA EXTRACTION
# =========================================================
def get_eligible_pq_buses():
    """Identifies all valid Type 1 Load Buses natively from the case."""
    ierr_b, b_nums = psspy.abusint(-1, 1, ["NUMBER"])
    ierr_t, b_types = psspy.abusint(-1, 1, ["TYPE"])
    if ierr_b != 0 or ierr_t != 0: return []
    pq_buses = [b for b, t in zip(b_nums[0], b_types[0]) if t == 1]
    return sorted(pq_buses)

def get_system_totals():
    p_loss = psspy.systot('LOSS')[1].real
    q_loss = psspy.systot('LOSS')[1].imag
    p_gen = psspy.systot('GEN')[1].real
    q_gen = psspy.systot('GEN')[1].imag
    p_load = psspy.systot('LOAD')[1].real
    q_load = psspy.systot('LOAD')[1].imag
    residual = p_gen - p_load - p_loss
    return p_gen, q_gen, p_load, q_load, p_loss, q_loss, residual

def get_bus_voltages():
    ierr_n, b_nums = psspy.abusint(-1, 2, ["NUMBER"])
    ierr_v, v_pu = psspy.abusreal(-1, 2, ["PU"])
    if ierr_n != 0 or ierr_v != 0 or not b_nums[0]: return None
    return {b: v for b, v in zip(b_nums[0], v_pu[0])}

# =========================================================
# CAPACITOR POSITION MAPPING
# =========================================================
def decode_position(continuous_pos, num_capacitors, max_mvar):
    discrete_pos = np.zeros_like(continuous_pos)
    top_indices = np.argsort(continuous_pos)[-num_capacitors:]

    for idx in top_indices:
        val = np.round(continuous_pos[idx] / STEP_MVAR) * STEP_MVAR
        val = np.clip(val, 0.0, max_mvar)  # CRITICAL FIX: Allows algorithm to intelligently choose 0 MVAr
        discrete_pos[idx] = val

    return discrete_pos

# =========================================================
# PARTICLE FITNESS ENGINE
# =========================================================
def evaluate_particle(position, candidate_buses, sav_file):
    if not load_case(sav_file):
        return {"feasible": False, "violation": float("inf"), "loss_mw": float("inf")}

    for bus, mvar in zip(candidate_buses, position):
        if mvar > 0:
            if not apply_shunt_capacitor(bus, mvar):
                return {"feasible": False, "violation": float("inf"), "loss_mw": float("inf")}

    if not run_loadflow():
        return {"feasible": False, "violation": float("inf"), "loss_mw": float("inf")}

    voltages = get_bus_voltages()
    if voltages is None:
        return {"feasible": False, "violation": float("inf"), "loss_mw": float("inf")}

    voltage_viol = sum(max(0.0, V_MIN - v, v - V_MAX) for v in voltages.values())
    loss_mw = psspy.systot('LOSS')[1].real
    feasible = (voltage_viol == 0.0)

    return {"feasible": feasible, "violation": voltage_viol, "loss_mw": loss_mw}

def fitness_tuple(result):
    """Lexicographic Hierarchy: 1. Feasibility -> 2. Min Violation -> 3. Min P_Loss"""
    if result["feasible"]:
        return (0, 0.0, result["loss_mw"])
    return (1, result["violation"], result["loss_mw"])

def get_change_string(metric, val_before, val_after):
    diff = val_after - val_before
    pct = abs(diff / val_before) * 100 if val_before != 0 else 0.0
    
    if abs(diff) < 1e-4: trend = "Remained unchanged"
    elif diff < 0: trend = f"Decreased by {pct:.2f}%"
    else: trend = f"Increased by {pct:.2f}%"
        
    return f"{metric:<28} : Base = {val_before:>10.4f}, Opt = {val_after:>10.4f} ({trend})"

# =========================================================
# MAIN EXECUTION
# =========================================================
def main():
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    sav_file = filedialog.askopenfilename(title="Select Base SAV File", filetypes=[("SAV files", "*.sav")])
    root.destroy()
    if not sav_file: return

    # --- FOLDER CREATION LOGIC ---
    sav_dir = os.path.dirname(sav_file)
    sav_basename = os.path.splitext(os.path.basename(sav_file))[0]
    output_folder = os.path.join(sav_dir, f"{sav_basename}_PSO_Results")
    
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    initialize_psse()
    os.chdir(sav_dir)

    if not load_case(sav_file) or not run_loadflow():
        messagebox.showerror("Power Flow Error", "Base case failed to converge.")
        return

    candidate_buses = get_eligible_pq_buses()
    num_candidates = len(candidate_buses)
    if num_candidates == 0:
        print("Error: No Type-1 PQ buses found.")
        return

    (b_pgen, b_qgen, b_pload, b_qload, b_ploss, b_qloss, b_presid) = get_system_totals()
    base_voltages = get_bus_voltages()
    base_vmin, base_vmax = min(base_voltages.values()), max(base_voltages.values())
    base_viol = sum(max(0.0, V_MIN - v, v - V_MAX) for v in base_voltages.values())

    # User Parameters
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    num_capacitors = simpledialog.askinteger("PSO Parameters", "Maximum capacitor banks to install:", minvalue=1, maxvalue=num_candidates, initialvalue=5, parent=root)
    if num_capacitors is None: return

    max_mvar = simpledialog.askfloat("PSO Parameters", "Maximum MVAr per installation:", minvalue=STEP_MVAR, initialvalue=100.0, parent=root)
    root.destroy()
    if max_mvar is None: return

    max_mvar = round(max_mvar / STEP_MVAR) * STEP_MVAR

    print("\n" + "=" * 65)
    print("CAPACITOR ALLOCATION (DISCRETE PSO)".center(65))
    print("=" * 65)
    print(f"Eligible Candidates  : {num_candidates} PQ Buses")
    print(f"Target Installations : Up to {num_capacitors} Distinct Buses")
    print(f"Max Capacity per Bus : {max_mvar:.1f} MVAr")
    print(f"PSO Parameters       : Swarm={SWARM_SIZE}, Iter={MAX_ITER}")
    print(f"Output Directory     : {output_folder}")
    print("-" * 65)
    
    velocity_limit = VELOCITY_LIMIT_FACTOR * max_mvar
    swarm = []

    # Initialize Swarm
    for i in range(SWARM_SIZE):
        # CRITICAL FIX: Particle 0 is anchored to the "Base Case" (0 MVAr). 
        if i == 0:
            continuous_pos = np.zeros(num_candidates)
        else:
            continuous_pos = np.random.uniform(0.0, max_mvar, num_candidates)
            
        position = decode_position(continuous_pos, num_capacitors, max_mvar)
        continuous_pos = position.copy()  
        velocity = np.random.uniform(-velocity_limit, velocity_limit, num_candidates)

        swarm.append({
            "continuous_pos": continuous_pos,
            "position": position,
            "velocity": velocity,
            "pbest_pos": position.copy(),
            "pbest_result": None
        })

    gbest_pos, gbest_result, best_feasible_loss = None, None, None
    best_effort_loss_history = []
    best_feasible_loss_history = []

    # PSO Execution
    for it in range(MAX_ITER):
        for particle in swarm:
            result = evaluate_particle(particle["position"], candidate_buses, sav_file)

            if particle["pbest_result"] is None or fitness_tuple(result) < fitness_tuple(particle["pbest_result"]):
                particle["pbest_result"] = result
                particle["pbest_pos"] = particle["position"].copy()

            if gbest_result is None or fitness_tuple(result) < fitness_tuple(gbest_result):
                gbest_result = result
                gbest_pos = particle["position"].copy()

        if gbest_result is not None and gbest_result["feasible"]:
            if best_feasible_loss is None or gbest_result["loss_mw"] < best_feasible_loss:
                best_feasible_loss = gbest_result["loss_mw"]

        best_effort_loss_history.append(gbest_result["loss_mw"])
        best_feasible_loss_history.append(np.nan if best_feasible_loss is None else best_feasible_loss)

        # Update Swarm State
        for particle in swarm:
            r1, r2 = np.random.rand(num_candidates), np.random.rand(num_candidates)
            particle["velocity"] = CHI * (particle["velocity"] + C1 * r1 * (particle["pbest_pos"] - particle["continuous_pos"]) + C2 * r2 * (gbest_pos - particle["continuous_pos"]))
            particle["velocity"] = np.clip(particle["velocity"], -velocity_limit, velocity_limit)
            
            particle["continuous_pos"] += particle["velocity"]
            particle["continuous_pos"] = np.clip(particle["continuous_pos"], 0.0, max_mvar)
            
            particle["position"] = decode_position(particle["continuous_pos"], num_capacitors, max_mvar)
            particle["continuous_pos"] = particle["position"].copy()  

        text = f"Best feasible P_loss = {gbest_result['loss_mw']:.4f} MW" if gbest_result and gbest_result["feasible"] else f"Best violation = {gbest_result['violation']:.4f} pu (Infeasible)"
        sys.stdout.write(f"\rIteration {it + 1:>3}/{MAX_ITER} | {text}")
        sys.stdout.flush()
    print()

    if gbest_pos is None:
        print("\nERROR: PSO did not produce a valid iteration.")
        return

    if not gbest_result["feasible"]:
        print("\n[WARNING] Strict feasibility not reached. Proceeding with Best Effort Solution...")

    # Final Independent Validation
    if not load_case(sav_file): return

    for bus, mvar in zip(candidate_buses, gbest_pos):
        if mvar > 0: apply_shunt_capacitor(bus, mvar)
    run_loadflow()

    opt_voltages = get_bus_voltages()
    (o_pgen, o_qgen, o_pload, o_qload, o_ploss, o_qloss, o_presid) = get_system_totals()
    opt_vmin, opt_vmax = min(opt_voltages.values()), max(opt_voltages.values())
    opt_viol = sum(max(0.0, V_MIN - v, v - V_MAX) for v in opt_voltages.values())
    opt_feasible = (opt_viol == 0.0)

    active_buses, active_mvars = [], []
    for bus, mvar in zip(candidate_buses, gbest_pos):
        if mvar > 0:
            active_buses.append(bus)
            active_mvars.append(mvar)

    total_mvar = sum(active_mvars)
    out_sav = os.path.join(output_folder, f"{sav_basename}_CAPACITOR_OPTIMIZED.sav")
    psspy.save(out_sav)

    # =========================================================
    # CREATE TEXT REPORT AND LOG IT
    # =========================================================
    report_lines = []
    def log(msg=""):
        print(msg)
        report_lines.append(msg)

    bus_keys = sorted(list(base_voltages.keys()))

    log("\n" + "="*65)
    log("INDEPENDENT SYSTEM VALIDATION SUMMARY".center(65))
    log("="*65)
    log(get_change_string("Total Generation P (MW)", b_pgen, o_pgen))
    log(get_change_string("Total Generation Q (MVAR)", b_qgen, o_qgen))
    log(get_change_string("Total Load P (MW)", b_pload, o_pload))
    log(get_change_string("Total Load Q (MVAR)", b_qload, o_qload))
    log(get_change_string("Active Power Loss (MW)", b_ploss, o_ploss))
    log(get_change_string("Reactive Power Loss (MVAR)", b_qloss, o_qloss))
    log(get_change_string("Minimum Voltage (pu)", base_vmin, opt_vmin))
    log(get_change_string("Maximum Voltage (pu)", base_vmax, opt_vmax))
    log(get_change_string("Total Voltage Violation (pu)", base_viol, opt_viol))

    if opt_feasible:
        log("\nBEST FEASIBLE CAPACITOR DEPLOYMENT")
    else:
        log("\nBEST-EFFORT INFEASIBLE CAPACITOR DEPLOYMENT")

    for bus, mvar in zip(active_buses, active_mvars):
        log(f" -> Bus {bus:>3} : {mvar:>5.1f} MVAr Installed")
    
    if len(active_buses) == 0:
        log(" -> No capacitors were deployed. Base case is the most optimal/safest state.")
    else:
        log(f"\n -> Total Added Reactive Capacity: {total_mvar:.1f} MVAr across {len(active_buses)} locations")

    log("\n" + "=" * 65)
    log("INDIVIDUAL BUS VOLTAGES (BEFORE vs AFTER)".center(65))
    log("=" * 65)
    for bus in bus_keys:
        log(f" -> Bus {bus:>3} : BEFORE = {base_voltages[bus]:.4f} pu  |  AFTER = {opt_voltages[bus]:.4f} pu")

    log("\nFINAL STATUS\n")
    pct_reduced = ((b_ploss - o_ploss) / b_ploss * 100.0) if b_ploss != 0 else 0.0
    if opt_feasible:
        log("Feasibility : FEASIBLE (Project constraint 0.95 <= Vi <= 1.05 pu strictly met)")
        log(f"Objective   : Active power loss reduced by {pct_reduced:.2f}%")
    else:
        log("Feasibility : INFEASIBLE (Grid voltage constraints remain violated)")
        log(f"Best effort : Active power loss reduced by {pct_reduced:.2f}%")
        log(f"Voltage     : Remaining constraint violation = {opt_viol:.4f} pu")
    
    log(f"\nExport SAV  : {out_sav}")

    # Write text report to file
    report_file_path = os.path.join(output_folder, "Optimization_Report.txt")
    with open(report_file_path, "w") as f:
        f.write("\n".join(report_lines))
    print(f"Export Log  : {report_file_path}")

    # =========================================================
    # PUBLICATION-GRADE FIGURES
    # =========================================================
    x_indices = np.arange(len(bus_keys))
    width = 0.35
    color_bef, color_aft = '#1f4e79', '#b22222'

    y_min_plot = min(base_vmin, opt_vmin, V_MIN) - 0.02
    y_max_plot = max(base_vmax, opt_vmax, V_MAX) + 0.02

    # Figure 1: Voltage Profile (Bar)
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(x_indices - width / 2, [base_voltages[b] for b in bus_keys], width, label='Before PSO', color=color_bef)
    ax1.bar(x_indices + width / 2, [opt_voltages[b] for b in bus_keys], width, label='After PSO', color=color_aft)
    ax1.axhline(V_MIN, color='black', linestyle=':', linewidth=1.5)
    ax1.axhline(V_MAX, color='black', linestyle=':', linewidth=1.5)
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(bus_keys, rotation=90)
    ax1.set_ylim(y_min_plot, y_max_plot)
    ax1.set_title("System Voltage Profile Comparison (Bar)")
    ax1.set_ylabel("Voltage Magnitude (pu)")
    ax1.legend(loc="upper right")
    format_publish_axis(ax1)
    fig1.tight_layout()
    fig1.savefig(os.path.join(output_folder, "Fig1_Voltage_Profile_Bar.png"))

    # Figure 2: Voltage Profile (Line)
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    ax2.plot(bus_keys, [base_voltages[b] for b in bus_keys], marker='s', color=color_bef, linestyle='-', linewidth=1.5, markersize=4, label='Before PSO')
    ax2.plot(bus_keys, [opt_voltages[b] for b in bus_keys], marker='o', color=color_aft, linestyle='-', linewidth=1.5, markersize=4, label='After PSO')
    ax2.axhline(V_MIN, color='black', linestyle=':', linewidth=1.5)
    ax2.axhline(V_MAX, color='black', linestyle=':', linewidth=1.5)
    ax2.set_xticks(bus_keys)
    ax2.set_xticklabels(bus_keys, rotation=90)
    ax2.set_title("System Voltage Profile Trajectory (Line)")
    ax2.set_ylabel("Voltage Magnitude (pu)")
    ax2.set_xlabel("Bus Number")
    ax2.legend(loc="lower right")
    format_publish_axis(ax2)
    ax2.grid(True, axis='both', color='#e0e0e0', linestyle='--', linewidth=0.5, alpha=0.7)
    fig2.tight_layout()
    fig2.savefig(os.path.join(output_folder, "Fig2_Voltage_Profile_Line.png"))

    # Figure 3: Optimal Capacitor Allocation
    fig3, ax3 = plt.subplots(figsize=(8, 4))
    if len(active_buses) > 0:
        x_cap = np.arange(len(active_buses))
        bars_cap = ax3.bar(x_cap, active_mvars, width=0.6, color=color_aft, edgecolor='black')
        ax3.set_xticks(x_cap)
        ax3.set_xticklabels([f"Bus {b}" for b in active_buses])
        ax3.set_title("Optimal PSO Capacitor Allocation & Sizing")
        ax3.set_ylabel("Installed Capacity (MVAr)")
        for bar in bars_cap:
            yval = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width() / 2, yval + max_mvar * 0.02, f"{yval:.0f}", ha='center', va='bottom', fontweight='bold')
        ax3.set_ylim(0, max_mvar * 1.2)
    else:
        ax3.set_title("No Capacitors Deployed by Algorithm")
        ax3.axis('off')
    format_publish_axis(ax3)
    fig3.tight_layout()
    fig3.savefig(os.path.join(output_folder, "Fig3_Capacitor_Allocation.png"))

    # Figure 4: Power Loss Breakdown
    fig4, ax4 = plt.subplots(figsize=(7, 4.5))
    metrics = ['Active Loss\n(MW)', 'Reactive Loss\n(MVAr)', 'Apparent Loss\n(MVA)']
    b_sloss = math.sqrt(b_ploss**2 + b_qloss**2)
    o_sloss = math.sqrt(o_ploss**2 + o_qloss**2)
    base_vals = [b_ploss, b_qloss, b_sloss]
    opt_vals = [o_ploss, o_qloss, o_sloss]
    x_pos = np.arange(len(metrics))
    
    bars1 = ax4.bar(x_pos - width / 2, base_vals, width, label='Before PSO', color=color_bef)
    bars2 = ax4.bar(x_pos + width / 2, opt_vals, width, label='After PSO', color=color_aft)
    ax4.set_xticks(x_pos)
    ax4.set_xticklabels(metrics)
    ax4.set_title("System Power Loss Reduction")
    ax4.set_ylabel("Loss Magnitude")
    max_val = max(max(base_vals), max(opt_vals))
    for bars in [bars1, bars2]:
        for bar in bars:
            yval = bar.get_height()
            ax4.text(bar.get_x() + bar.get_width() / 2, yval + max_val * 0.02, f'{yval:.2f}', ha='center', va='bottom', fontsize=8.5, fontweight='bold')
    
    ax4.set_ylim(0, max_val * 1.35)
    ax4.legend(loc="upper right")
    format_publish_axis(ax4)
    fig4.tight_layout()
    fig4.savefig(os.path.join(output_folder, "Fig4_Power_Loss_Bar.png"))

    # Figure 5: Convergence Curve (Dual Line)
    fig5, ax5 = plt.subplots(figsize=(8, 4))
    iterations = np.arange(1, MAX_ITER + 1)
    
    ax5.plot(iterations, best_effort_loss_history, color='#1f4e79', linestyle='--', linewidth=1.5, label='Best Effort Search (Infeasible allowed)')
    
    if not np.isnan(best_feasible_loss_history).all():
        ax5.plot(iterations, best_feasible_loss_history, color=color_aft, linestyle='-', linewidth=2.5, label='Best Feasible Solution')
        ax5.set_title("PSO Objective Convergence (Active Power Loss)")
    else:
        ax5.set_title("PSO Objective Convergence (Warning: No Feasible Solutions Found)")
        ax5.text(0.5, 0.5, 'All Evaluated Solutions Remain Infeasible\n(Showing Best-Effort Trajectory)', transform=ax5.transAxes, ha='center', va='center', alpha=0.6, fontsize=11, color='gray', fontweight='bold')

    ax5.set_xlabel("Iteration")
    ax5.set_ylabel("Active Power Loss (MW)")
    ax5.legend(loc="upper right")
    format_publish_axis(ax5)
    fig5.tight_layout()
    fig5.savefig(os.path.join(output_folder, "Fig5_PSO_Convergence.png"))

    print(f"Export Plots: All 5 figures saved in {output_folder}")
    plt.show()

if __name__ == "__main__":
    main()