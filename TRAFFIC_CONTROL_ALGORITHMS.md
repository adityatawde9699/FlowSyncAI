# Traffic-control algorithms

## Decision rule

The controller selects between two non-conflicting phase groups, NS and EW. Let `q(i,a)` be the local queued vehicles on approach `a` at intersection `i`, and `q(d(i,a))` the current queue on the connected downstream approach. Pressure is:

`P(i, φ) = Σ[a in φ] (q(i,a) − 0.7 q(d(i,a)))`.

Max Pressure selects the phase with maximum `P`. The corridor fallback routes N/S entries into a selected E/W direction; its downstream queue estimate averages the connected corridor queues. In the SUMO grid, N/S movements exit to an unsignalized side-road boundary, so those movements have zero downstream signal queue. W/E approaches use the next connected signal's same-direction incoming queue.

Each intersection agent sees its own approach state and the immediate upstream/downstream signal neighbor state. A failed communication link removes neighbor state and switches that agent to local Max Pressure. No agent receives the full network state.

FlowSync adds local contextual terms:

`S(i, φ) = P(i, φ) + 50 E(i, φ) + 2.5 Wp(i, φ)/30 − 6 Σ[k in φ] severity(k)`

where `E` counts queued emergency vehicles, `Wp` is waiting pedestrian count for the phase, and `severity(k) ∈ [0,1]` is an active incident on an approach in the phase. The larger score is requested. Tunable constants are implementation parameters; they have not been optimized or experimentally validated.

## Baselines

- **Fixed-time:** requests NS/EW in alternating 40-second slots in the fallback. SUMO shortens or extends the active generated green to follow the fixed request while leaving generated clearance states in sequence.
- **Actuated:** requests the phase with the larger local queue.
- **Max Pressure:** requests the phase with the larger upstream-minus-downstream queue score.
- **FlowSync:** uses the same pressure with incident, emergency and pedestrian context.

All requests share the same safety path. The fallback interlock enforces at least 10 seconds green, then 3 seconds yellow and 1 second all-red before a new green. Pedestrian calls wait for minimum green, then receive yellow, all-red, a 7-second all-red walk interval and a 5-second pedestrian-clearance interval before vehicle green resumes. Walk calls are grouped; late arrivals wait for a later call. Emergency vehicles never set a signal directly and receive no priority while a conflicting vehicle or pedestrian clearance is active.

SUMO uses the signal program generated with the network, including its compatible vehicle and crossing phases. TraCI can shorten/extend only the currently active green; it does not write arbitrary light vectors or jump across yellow/all-red phases. The generated program's safety behavior still requires runtime validation on an installed SUMO build.

## Limits and contribution

The controller uses two phase groups and does not model protected turning movement plans in the fallback. The fallback is a point-queue model with simplified route choice. SUMO uses a generated grid and fixed origin/destination demand; it is not a calibrated OSM traffic network. The heuristic combines known queue-pressure and priority concepts. Its research contribution must be established by paired comparisons and ablations (remove incident, emergency, pedestrian, downstream and decentralization terms), not by labeling the combination novel.
