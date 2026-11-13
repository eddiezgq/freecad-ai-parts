# Mainboards, memory modules, structural parts and racks

## Mainboards: one SMT line

Same steps as the PCB plant (paste printing → SPI → placement → reflow → AOI) plus **X-ray**: CPU sockets, chipsets and DRAM are BGAs whose joints sit under the package, so only X-ray shows the **voids** in them.
Each board records three items at ICT: paste thickness, worst BGA void ratio, CPU core voltage at power-on.

## Memory modules: the same SMT line + memory tester

Finished modules get a read/write test that measures **timing margin** (how far the signal is from failing, in ps). The tester has 8 sockets used in turn — recording which socket tested each module is the key to tracing false rejects from a bad socket.

## Structural parts

- **Desktop and server chassis**: laser cutting → press brake → self-clinching standoffs → powder coating. Measured: bend angle, mounting-hole position, coating thickness — holes off position and the board or PSU will not fit.
- **Notebook housings**: machining center mills the A and C covers → anodizing. Measured: flatness and anodic film thickness.

## Systems

Thermal paste (dispenser, recorded as dp-1 or dp-2) → assembly → POST & OS imaging → burn-in (4 h desktops and notebooks, 12 h servers) → system test. See [System burn-in curves](/burn-in).

## Racks (computing center / data center delivery)

16 servers racked and cabled → full-load rack test: rack power, rear-door heat exchanger air temperature rise, switch link errors → rack crated and shipped.
How to design the computing center itself (rack count, power, cooling, PUE) is in the computer plant's design cases.
