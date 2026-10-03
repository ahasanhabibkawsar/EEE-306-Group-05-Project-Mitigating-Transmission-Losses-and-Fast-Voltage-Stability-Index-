import os
import sys
import tkinter as tk
from tkinter import filedialog
def setup_psse_env():
    paths = [r"C:\Program Files\PTI\PSSE36\36.6\PSSPY313", r"D:\Program Files\PTI\PSSE36\36.6\PSSPY313"]
    psse_path = next((p for p in paths if os.path.exists(p)), None)
    if not psse_path:
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        psse_path = filedialog.askdirectory(title="Select PSS/E Python Folder")
        root.destroy()
        if not psse_path: sys.exit()

    sys.path.append(psse_path)
    os.environ['PATH'] = psse_path + ';' + os.environ.get('PATH', '')
    if hasattr(os, 'add_dll_directory'): os.add_dll_directory(psse_path)
    
    bin_path = psse_path.replace("PSSPY313", "PSSBIN")
    if os.path.exists(bin_path):
        sys.path.append(bin_path)
        os.environ['PATH'] = bin_path + ';' + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'): os.add_dll_directory(bin_path)

setup_psse_env()
import psspy, redirect

def run_practical_fvsi_analysis():
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    sav_file = filedialog.askopenfilename(title="Select Base SAV File", filetypes=[("SAV files", "*.sav")])
    root.destroy()
    if not sav_file: return
    
    redirect.psse2py()
    psspy.psseinit(80000)
    
    _i, _f = psspy.getdefaultint(), psspy.getdefaultreal()
    psspy.progress_output(2, "NUL", [_i, _i])
    psspy.prompt_output(2, "NUL", [_i, _i])
    psspy.report_output(2, "NUL", [_i, _i])
    
    if psspy.case(sav_file) != 0 or psspy.fnsl([0,0,0,0,1,0,0,0]) != 0 or psspy.solved() != 0: 
        print("Error: Could not load or solve base case.")
        return
    _, busnum  = psspy.abusint(-1, 2, ["NUMBER"])
    _, busvolt = psspy.abusreal(-1, 2, ["PU"])
    bus_idx = {b: i for i, b in enumerate(busnum[0])} if busnum else {}

    _, from_bus = psspy.abrnint(-1, 1, 3, 2, 1, ["FROMNUMBER"])
    _, to_bus   = psspy.abrnint(-1, 1, 3, 2, 1, ["TONUMBER"])
    _, ckt_ids  = psspy.abrnchar(-1, 1, 3, 2, 1, ["ID"])

    results = []
    step_size_mvar = 3.0

    for fb, tb, cid in zip(from_bus[0], to_bus[0], ckt_ids[0]):
        if fb not in bus_idx or tb not in bus_idx: continue
        if psspy.brnint(fb, tb, cid, "STATUS")[1] != 1: continue
        
        err, rx = psspy.brndt2(fb, tb, cid, "RX")
        if err != 0 or rx.imag <= 0: continue

        R, X = rx.real, rx.imag
        
        psspy.case(sav_file)
        psspy.fnsl([0,0,0,0,1,0,0,0])
        
        _, s_from_base = psspy.brnflo(fb, tb, cid)
        _, s_to_base = psspy.brnflo(tb, fb, cid)

        if s_from_base.real >= 0:
            send_bus, recv_bus = fb, tb
            V_send = busvolt[0][bus_idx[fb]]
            V_recv = busvolt[0][bus_idx[tb]]
            base_Q_recv = -s_to_base.imag
            recv_is_to_bus = True
        else:
            send_bus, recv_bus = tb, fb
            V_send = busvolt[0][bus_idx[tb]]
            V_recv = busvolt[0][bus_idx[fb]]
            base_Q_recv = -s_from_base.imag
            recv_is_to_bus = False

        if base_Q_recv <= 0 or V_send < 1e-6: continue

        base_P_flow = abs(s_from_base.real)
        base_P_loss = s_from_base.real + s_to_base.real
        base_Q_loss = s_from_base.imag + s_to_base.imag
        base_fvsi = (4.0 * (R**2 + X**2) * (base_Q_recv / 100.0)) / (V_send**2 * X)

        load_id = None
        for lid in ['1 ', '2 ', '3 ', 'A ', 'B ', 'C ']:
            ierr, _ = psspy.loddt2(recv_bus, lid, 'MVA', 'ACT')
            if ierr == 0:
                load_id = lid
                break

        if not load_id: continue

        ierr, cmpval = psspy.loddt2(recv_bus, load_id, 'MVA', 'ACT')
        original_p = cmpval.real
        original_q = cmpval.imag
        
        added_q = 0.0
        last_valid_Q_recv = base_Q_recv
        
        while True:
            added_q += step_size_mvar
            new_q = original_q + added_q
            
            psspy.load_data_6(recv_bus, load_id, [_i]*7, [original_p, new_q, _f, _f, _f, _f, _f, _f])
            psspy.fnsl([0, 0, 0, 0, 1, 0, 0, 0])
            
            if psspy.solved() != 0:
                break
                
            _, cur_s_from = psspy.brnflo(fb, tb, cid)
            _, cur_s_to = psspy.brnflo(tb, fb, cid)
            
            if recv_is_to_bus:
                last_valid_Q_recv = -cur_s_to.imag
            else:
                last_valid_Q_recv = -cur_s_from.imag

        actual_q_margin = last_valid_Q_recv - base_Q_recv

        results.append({
            "send_bus": send_bus, "recv_bus": recv_bus, "fvsi": base_fvsi,
            "V_send": V_send, "V_recv": V_recv, "P_flow": base_P_flow, 
            "Q_recv": base_Q_recv, "Q_max": last_valid_Q_recv, "Q_margin": actual_q_margin,
            "P_loss": base_P_loss, "Q_loss": base_Q_loss
        })
        
    if not results: 
        print("No valid lines found for analysis.")
        return
        
    results.sort(key=lambda k: k["fvsi"], reverse=True)
    
    for res in results:
        print(f"From bus {res['send_bus']} to {res['recv_bus']}")
        print(f"  Base FVSI       = {res['fvsi']:.4f}")
        print(f"  V_send (pu)     = {res['V_send']:.4f}")
        print(f"  V_recv (pu)     = {res['V_recv']:.4f}")
        print(f"  P_flow (MW)     = {res['P_flow']:.4f}")
        print(f"  Q_recv (MVAR)   = {res['Q_recv']:.4f}")
        print(f"  Q_max (MVAR)    = {res['Q_max']:.4f} (Actual network limit)")
        print(f"  Q_margin (MVAR) = {res['Q_margin']:.4f} (Actual margin)")
        print(f"  P_loss (MW)     = {res['P_loss']:.4f}")
        print(f"  Q_loss (MVAR)   = {res['Q_loss']:.4f}\n")

    if results:
        top = results[0]
        print("RESULT ANALYSIS")
        print(f"Most critical corridor: Bus {top['send_bus']} to {top['recv_bus']} (FVSI = {top['fvsi']:.4f})")
        print(f"This line can absorb only {top['Q_margin']:.2f} MVAR more before experiencing collapse.")

        if top['fvsi'] < 0.2:
            print("System is highly secure.")
        elif top['fvsi'] < 0.5:
            print("Corridor is stressed.")
        elif top['fvsi'] < 0.8:
            print("Corridor approaching voltage stability limit.")
        else:
            print("Corridor operating dangerously close to voltage collapse.")

if __name__ == "__main__":
    run_practical_fvsi_analysis()