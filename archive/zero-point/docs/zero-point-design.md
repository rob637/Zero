# Zero-Point: Design and Technical Specification

## 1. Vision

Zero-Point is a deterministic multiphysics toy-box puzzle game.

Core promise:
- Players do not solve a scripted puzzle path.
- Players manipulate physical laws until a solution becomes inevitable.
- The sandbox should feel alive, reactive, and legible under extreme parameter changes.

Design mandate:
- Toy first, puzzle second.
- Every level supports multiple valid physical strategies.

## 2. Pillars

1. Deterministic Simulation
- Same input timeline must produce identical outcomes across runs and platforms.

2. Coupled Physics
- Global constants affect multiple systems simultaneously.
- Slider changes should create second-order consequences, not isolated effects.

3. Emergence Over Scripts
- Prefer system interactions over handcrafted one-off events.

4. Readable Chaos
- Even at extreme values, outcomes should remain understandable with strong feedback.

## 3. Core Mechanic: The Chaos Table

The player controls five global sliders in real time.

| Constant | Symbol | Primary Domain | High (100) | Low (0) |
|---|---|---|---|---|
| Gravity | g | Weight, buoyancy, settling | Objects crush/shatter under self-weight | Near-floating Brownian drift |
| Friction | mu | Motion damping, heat generation | Kinetic energy converts quickly to thermal energy | Near-perfect glide/perpetual motion |
| Viscosity | eta | Fluid and air drag | Air/fluid feel like molasses | Vacuum-like movement |
| Elasticity | e | Collision energy retention | Super-bouncy impacts (energy gain allowed in game feel layer) | Sticky clay-like collisions |
| Time Scale | t | Simulation rate and perception | Bullet-time, near frame-step precision | Fast-forward chaos and jitter pressure |

### Coupling Rules (Mandatory)

- Friction and impact speed increase internal energy.
- Internal energy drives thermal expansion.
- Thermal thresholds trigger phase transitions.
- Gravity alters effective spring load on procedural growth.
- Viscosity changes drag on particles, rigid bodies, and plant motion.
- Time scale affects both integration step policy and presentation layer (audio/visual).

## 4. Emergent Systems

### 4.1 Thermal Expansion and Phase Shifts

Each dynamic object has:
- mass
- temperature/internal energy
- thermal expansion coefficient
- phase thresholds (solid -> liquid)

Behavior:
- Energy sources: friction work, inelastic collisions, external scripted heaters (optional later).
- Expansion: collider scale grows as temperature rises.
- Transition: at threshold, object converts from rigid body to particle-fluid representation.
- Cooling: passive dissipation to environment; rate impacted by viscosity/time scale tuning.

Implementation notes:
- Keep conversion deterministic by fixed threshold checks in fixed update order.
- For rigid->fluid conversion, seed particles from deterministic point set (same seed each run).

### 4.2 Procedural Growth via L-Systems + Springs

Plants are simulation objects, not animations.

Structure:
- Branches are segments connected by spring joints.
- Growth increases rest length and may spawn child segments per grammar.
- Growth rate depends on available "growth energy" and global constants.

Physics interaction:
- Growth generates force through constraint resolution.
- Under low gravity, mature structures can lift very heavy rigid bodies.
- Under high viscosity, growth visibly slows due to drag load.

Determinism notes:
- Use seeded RNG per level and fixed grammar expansion order.
- Resolve joint constraints in stable, deterministic sequence.

## 5. Deterministic Engine Requirements

Preferred options:
- Rapier (Rust/Wasm) with fixed-step deterministic configuration.
- Custom Verlet/PBD solver where full update order is controlled.

Non-negotiables:
- Fixed tick rate (for example, 120 Hz simulation tick).
- Input sampling and replay recorded per tick.
- Stable object IDs and deterministic iteration order.
- No frame-rate-dependent force application.
- Cross-platform float strategy:
  - either strict deterministic math subset,
  - or fixed-point for critical state transitions.

Recommended architecture:
- Simulation thread/process: authoritative fixed-step world state.
- Presentation layer: interpolated rendering and post-processing.
- Event bus: deterministic events emitted from sim to audio/VFX.

## 6. The Juice Layer

### 6.1 Dynamic Audio

Map parameters to music and SFX:
- Time scale t:
  - lower t (bullet-time) -> lower BGM pitch, longer tails
  - higher t -> tighter envelope, brighter transients
- Viscosity eta:
  - high eta -> wetter reverb, low-pass damping
  - low eta -> dry, sharp response

Audio implementation:
- Use smoothed parameter ramps to avoid zipper noise.
- Drive from normalized slider values and key simulation events.

### 6.2 Visual Feedback

Post-process effects increase near unstable/extreme states:
- Bloom intensity with collision energy and thermal load.
- Chromatic aberration near impossible parameter combinations.
- Optional screen-space distortion under extreme viscosity/time-scale mismatch.

Rule:
- Effects must communicate state risk and possibility, not just look dramatic.

## 7. Level Design Framework (Non-Linear by Design)

Each level must support at least three distinct solution archetypes:
- Heavy Way: high gravity and force-driven routing.
- Bouncy Way: high elasticity and rebound chains.
- Slow-Motion Way: low time scale and precision manipulation.

Validation checklist for every level:
- At least 3 solution families are intentionally test-verified.
- No single slider is mandatory for success.
- At least one solution uses an emergent system (thermal or growth).

## 8. MVP: Comfort Test Room

MVP room contains:
- Seed (objective object)
- Pot (goal trigger)
- Chaos Table with all five sliders
- Minimal geometry to allow trajectories and rebounds

Success condition:
- Seed enters pot volume and remains for N stable ticks.

Comfort test pass criteria:
- Testers spend at least 10 minutes experimenting with sliders.
- Reported experience trends toward satisfying, not frustrating.

Suggested measurable MVP KPIs:
- Median time-to-first-success: 2-8 minutes.
- Retry count before success: at least 3 (signals experimentation).
- Distinct slider profiles used before success: at least 2.

## 9. Engineering Plan

### Phase 1: Deterministic Core (Week 1-2)
- Implement fixed-step loop and deterministic state container.
- Add rigid body primitives and collision callbacks.
- Implement Chaos Table parameter injection into solver.
- Build replay harness: record inputs, replay, assert state hash.

Exit criteria:
- 100 identical replays for same seed/input sequence.

### Phase 2: Coupled Systems (Week 3-4)
- Add thermal model and expansion.
- Add deterministic solid->fluid transition.
- Add initial procedural plant growth using spring chains.

Exit criteria:
- Demonstrable interactions where changing one slider affects at least two systems.

### Phase 3: Juice + UX (Week 5)
- Audio parameter mapping to t and eta.
- Post-processing ramps tied to instability metrics.
- Finalize slider UX: labels, tooltips, reset/preset controls.

Exit criteria:
- Players can understand why outcomes changed after slider edits.

### Phase 4: Comfort Test Content (Week 6)
- Build single room and win logic.
- Add telemetry for KPI capture.
- Run 5-10 playtests and tune defaults/ranges.

Exit criteria:
- Comfort test criteria met.

## 10. Data Model (MVP)

Example simulation entity fields:
- id (stable)
- transform
- velocity/angularVelocity
- mass
- material (friction, restitution/elasticity)
- internalEnergy
- temperature
- phase
- growthState (for plants)

Global state:
- chaos.g
- chaos.mu
- chaos.eta
- chaos.e
- chaos.t
- tick
- rngSeed

## 11. Risks and Mitigations

1. Non-determinism across machines
- Mitigation: replay hash tests in CI, deterministic math policy, fixed update order.

2. Sandbox feels random instead of expressive
- Mitigation: strong state feedback (audio/VFX/UI), parameter smoothing, capped instability.

3. Emergent systems are expensive
- Mitigation: cap particle counts, LOD for fluids/plants, broadphase optimization.

4. Slider space has dead zones
- Mitigation: non-linear response curves and per-level tuning windows.

## 12. Test Strategy

Automated:
- Determinism replay suite (state hash by tick).
- Property tests for energy and phase thresholds.
- Regression scenes for known solution archetypes.

Manual:
- Comfort test protocol with think-aloud sessions.
- Track frustration markers:
  - repeated "I don't know why that happened"
  - abrupt abandonment before 5 minutes

## 13. Definition of Done for MVP

MVP is done when all are true:
- Single room playable with seed/pot/sliders.
- Deterministic replay passes for shipped scene.
- At least three distinct successful strategy patterns observed in playtest.
- Majority of testers report the 10-minute loop as satisfying.
