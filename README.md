# Mitigating Transmission Losses and FVSI-Evaluated Voltage Collapse using GA and PSO in PSS®E

**EEE 306 – Power System I Laboratory · Final Project · Group 05, Section B2 (Level 3 Term 1, January 2026)**
Department of Electrical and Electronic Engineering, Bangladesh University of Engineering and Technology (BUET)

This repository holds the Python programs, test cases, raw results and report for our project. The programs drive **Siemens PSS®E** through its `psspy` API to:

1. **Screen line stability** with the Fast Voltage Stability Index (FVSI) and measure each line's real reactive-power margin.
2. **Optimise transformer tap positions** with a discrete **Genetic Algorithm (GA)**.
3. **Choose where to put shunt capacitor banks and how big to make them** (5 MVAr steps) with a discrete **constriction-factor Particle Swarm Optimization (PSO)**.

Every candidate solution is checked with a full Newton–Raphson AC load flow in PSS®E. Candidates are ranked by a *lexicographic* fitness: feasibility first, then total voltage violation, then active power loss. Because of this ranking, the search still gives a useful best-effort answer when the stressed grid cannot be brought fully inside the 0.95–1.05 pu band.

---

## Key results

GA and PSO were each run separately, starting from the same stressed base case.

| System / state | P<sub>loss</sub> (MW) | V<sub>min</sub> (pu) | Σ voltage violation (pu) | Max FVSI (line) | Q-margin of critical line |
|---|---|---|---|---|---|
| IEEE 14 – stressed base | 71.03 | 0.6474 | 2.6229 | 0.3727 (1→5) | 0 MVAr |
| IEEE 14 – GA taps | 62.14 (−12.5 %) | 0.8008 | 1.2121 | 0.2896 (1→5) | 19.2 MVAr |
| IEEE 14 – PSO, K = 3, 50 MVAr (bus 4: 50, bus 5: 45, bus 7: 5) | **47.42 (−33.2 %)** | 0.8905 | 0.2074 | 0.1208 (7→9) | 17.5 MVAr |
| IEEE 39 – stressed base | 124.75 | 0.8193 | 1.0267 | 0.2479 (2→3) | 0 MVAr |
| IEEE 39 – GA taps | 99.21 (−20.5 %) | 0.9242 | 0.1307 | 0.2104 (19→16) | 418 MVAr |
| IEEE 39 – PSO, K = 12, 100 MVAr (1110 MVAr at 12 buses) | **85.02 (−31.9 %)** | 0.9820 | 0.0135 | 0.1005 (1→39) | 206 MVAr |

- After PSO, every IEEE 39 load bus lies inside 0.95–1.05 pu. The small violation that remains is generator bus 36, whose set-point is 1.0635 pu. In IEEE 14, slack bus 1 is fixed at 1.06 pu. Neither taps nor capacitors can move a generator set-point, so strict feasibility is physically impossible in these cases.
- Allowing the PSO to use every PQ bus (K = 9 for IEEE 14, K = 29 for IEEE 39) gave the same result on IEEE 14. On IEEE 39 it gave a slightly worse result: 86.28 MW. With K = 29 the search space is about 10³⁸ configurations, which is far too large for the budget of 14,400 load-flow evaluations (120 × 120) used in that run.

---

## Repository structure

```
.
├── code/                         Python programs (run with PSS®E's Python)
│   ├── FVSI-Collapse Analysis.py   FVSI ranking + measured reactive margin of every loaded line
│   ├── IEEEtxfTapGE.py             discrete GA for transformer tap ratios
│   └── PSOcapacitor.py             discrete constriction-factor PSO for shunt capacitors
├── cases/                        stressed PSS®E cases used in the study
│   ├── IEEE14Data.sav
│   └── IEEE39Data.sav
├── results/                      raw outputs produced by the programs
│   ├── IEEE14_GA/                  Optimization_Report.txt, figures, *_TAP_OPTIMIZED.sav
│   ├── IEEE14_PSO_K3_50MVAr/       Optimization_Report.txt, figures, *_CAPACITOR_OPTIMIZED.sav
│   ├── IEEE14_PSO_K9_50MVAr/
│   ├── IEEE39_GA/
│   ├── IEEE39_PSO_K12_100MVAr/
│   ├── IEEE39_PSO_K29_100MVAr/
│   └── FVSI/                       FVSI logs (base, after GA, after PSO) – .txt and .docx
├── report/
│   ├── EEE306_G05_Final_Project_Report.docx
│   └── EEE306_G05_Presentation.pptx
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Requirements

| Item | Version used |
|---|---|
| Siemens PSS®E | 36.6 (Xplore academic edition, ≤ 50 buses, is enough for both cases) |
| Python | 3.13 (the `PSSPY313` build of `psspy` that ships with PSS®E) on Windows |
| Python packages | `numpy`, `matplotlib`; `tkinter` is bundled with Python |

```bash
pip install -r requirements.txt
```

`psspy` and `redirect` come with PSS®E itself and **cannot** be installed with pip.

---

## How to run

1. **Set the PSS®E paths.** If PSS®E is not installed in `C:\Program Files\PTI\PSSE36\36.6`, edit `PSSPY_PATH` and `PSSBIN_PATH` at the top of `IEEEtxfTapGE.py` and `PSOcapacitor.py`. `FVSI-Collapse Analysis.py` also checks `D:\` and asks you for the folder if it can't find PSS®E.
2. **Screen line stability.**
   ```bash
   python "code/FVSI-Collapse Analysis.py"
   ```
   Choose a `.sav` file in the dialog. The program prints every loaded line ranked by FVSI, with V, P, Q, Q<sub>max</sub> and Q<sub>margin</sub>, and names the most critical corridor.
3. **Optimise transformer taps (GA).**
   ```bash
   python code/IEEEtxfTapGE.py
   ```
   Choose the `.sav` file. By default it runs a population of 50 for 50 generations (`POP_SIZE`, `MAX_GEN` at the top of the script; the results in `results/` and the report were obtained with 120 × 120). At the end it prints a summary, the tap changes and the bus voltages, and saves `<case>_TAP_OPTIMIZED.sav`. The six figures open in windows; save them from there.
4. **Optimise shunt capacitors (PSO).**
   ```bash
   python code/PSOcapacitor.py
   ```
   Choose the `.sav` file, then enter the maximum number of capacitor sites **K** and the maximum MVAr per site. The program creates `<case>_PSO_Results/`, which contains `Optimization_Report.txt`, `<case>_CAPACITOR_OPTIMIZED.sav` and five PNG figures. By default the swarm has 60 particles and runs 60 iterations (`SWARM_SIZE`, `MAX_ITER`; the reported results used 120 × 120).
5. **Verify.** Run the FVSI script again on the optimised `.sav` file and compare the new FVSI values and reactive margins with the base case.
The tuning constants (population/swarm size, iterations, P<sub>c</sub>, P<sub>m</sub>, elitism, tournament size, c<sub>1</sub>, c<sub>2</sub>, velocity limit, capacitor step, voltage limits) are at the top of each script. The random seed is fixed at 42 so runs can be reproduced.

---

## Method summary

| Stage | Details |
|---|---|
| Load flow | `psspy.fnsl([0,0,0,0,1,0,0,0])`: tap adjustment off (GA taps are held), switched shunts on, reactive limits applied immediately |
| Fitness | tuple `(infeasible, Σ voltage violation, P_loss)`, compared element by element; no penalty weights to tune |
| GA | integer tap-index chromosomes on each transformer's RMIN–RMAX–NTPOSN grid; tournament k = 5; single-point crossover P<sub>c</sub> = 0.95; ±1-step mutation P<sub>m</sub> = 0.35; elitism 6; chromosome 0 = base taps |
| PSO | c<sub>1</sub> = c<sub>2</sub> = 2.05, constriction χ = 0.7298; \|v\| ≤ 0.5 Q<sub>max</sub>; keep the K largest coordinates, round to 5 MVAr, clip to [0, Q<sub>max</sub>]; particle 0 = no capacitors |
| FVSI | FVSI<sub>ij</sub> = 4 Z² Q<sub>j</sub> / (V<sub>i</sub>² X). Reactive margin is measured by adding 3 MVAr at a time to the receiving-bus load until the load flow diverges |

---

## Team

| Member | ID | Contribution |
|---|---|---|
| Mahfuz Alam Tonmoy | 2206116 | FVSI weak-line screening; modelling/validation of the IEEE 14- and 39-bus systems |
| Md. Shibli Noman | 2206117 | Project coordination; Python–PSS®E (psspy) bridge, automated load flows, stressed base cases |
| Md. Abdullah Al-Noman | 2206118 | GA tap optimisation: encoding, tournament selection, crossover, mutation, elitism |
| Md. Ahasan Habib Kawsar | 2206119 | PSO capacitor allocation: swarm design, 5 MVAr discretisation, constriction-factor tuning |
| Md. Kawsar Ahmed | 2206122 | Project coordination: planning, milestones, integration of GA and PSO into one pipeline |
| Sadiq Sayeed Raha | 2206128 | Results analysis and plots; societal, environmental and ethical impact assessment |
| Aritra Chowdhury | 2206129 | Results analysis, report, slides and references |

**Course instructors:** Azazul Islam and Asikul Islam Asik, Lecturers, Department of EEE, BUET.

---

## Links

- Presentation / demonstration material: [Google Drive](https://drive.google.com/file/d/1S16e6D9CnCVc4tx-kQVD8_oTBZiHku-k/view?usp=sharing)
- YouTube video: *to be added*

## Main references

1. I. Musirin and T. K. Abdul Rahman, "Novel fast voltage stability index (FVSI) for voltage stability analysis in power transmission system," SCOReD 2002.
2. M. F. Mohammad Kamal, T. K. Abdul Rahman and I. Musirin, "Application of improved genetic algorithms for loss minimisation in power system," PECon 2004.
3. A. G. Bakirtzis et al., "Optimal power flow by enhanced genetic algorithm," *IEEE Trans. Power Systems*, 17(2), 2002.
4. M. Clerc and J. Kennedy, "The particle swarm – explosion, stability, and convergence in a multidimensional complex space," *IEEE Trans. Evol. Comput.*, 6(1), 2002.
5. Siemens PTI, *PSS®E 36 Program Application Guide* and *psspy API documentation*.

PSS®E is a registered trademark of Siemens. PSS®E itself is not included in this repository; you need your own licence to run the programs.
