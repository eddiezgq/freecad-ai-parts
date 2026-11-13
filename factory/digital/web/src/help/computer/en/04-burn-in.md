# System burn-in and burn-in curves

In the burn-in room every system runs a **full-load stress test**: 50 minutes of load and 10 idle every hour, logging CPU temperature, fan speed and system power once a minute.
**CPU full-load temperature and average burn-in power are calculated from the curves**, so curves and measurement records always agree.

## Reading the “System burn-in curves” page

Open [System burn-in curves](/burn-in); the list on the left shows recent systems, filterable by model and dispenser. Click one to see its three curves (shaded = load periods):

| Where | Normal | Abnormal means |
|---|---|---|
| CPU temperature | Reaches a plateau quickly under load, with margin below the limit (red dashes) | High plateau, fast rise → heat cannot get out: check the thermal paste layer (dose) first |
| Fan speed | Rises to 70–80 % under load, drops at idle | At maximum from the start yet still hot → not the fans; the thermal resistance is high |
| System power | Two steady levels, load and idle | Large ripple → check the PSU |
| Total thermal resistance | Shown per CPU, with the paste layer's share | Paste layer much larger than for the same model → too little paste |

Above the list: **average margin of full-load temperature to the limit for systems done by each dispenser** — if only one has little margin, that dispenser is the problem.

## Why “longer burn-in” and “faster fans” do not fix it

Too little paste is a **heat-path** problem: longer burn-in does not lower the resistance; faster fans pull the temperature down a little but make more noise, and in a warm room at the customer it overheats again — that hides the problem, it does not correct it.
The real fix: clean the dispenser needle, check the dose by weighing, open the systems already built and re-apply paste, then retest.
