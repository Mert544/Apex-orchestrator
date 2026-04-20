# Synthetic Shop Demo

This is a deliberately small but imperfect demo project used to exercise Epistemic Orchestrator.

It contains:

- an entrypoint
- a service hub with multiple dependencies
- auth and payment surfaces
- configuration coupling
- partial tests only
- a CI workflow

Run the orchestrator against it with:

```bash
export EPISTEMIC_TARGET_ROOT=$(pwd)/examples/synthetic_shop
python -m app.main
```
