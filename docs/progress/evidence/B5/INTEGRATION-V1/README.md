# B5 offline integration v1 evidence

The integration branch was created from `d8ad99a` and merged in this order:

```text
batch/b5-m1-m2 -> batch/b5-vision -> batch/b5-demo
```

Source and merge commits are recorded in `docs/progress/B5-INTEGRATION-V1.md`.

The following commands were run in `/home/zzq/PTR/worktrees/b5-offline-integration`:

```text
python3 -m py_compile ...                         PASS
python3 -m unittest -v tests/b5/test_m1_m2_route_sim.py tests/b4_prep/test_m1_m2_motion_sim.py  PASS (12)
python3 -m unittest -v tests/test_calibration_tools.py tests/test_d405_quality_gate.py tests/test_camera_extrinsics_candidate.py tests/test_offline_vision_pipeline.py tests/test_build_offline_vision_paper_results.py  PASS (30)
python3 -m unittest -v tests/test_b5_demo_flow.py  PASS (8)
python3 -m unittest discover -s tests/b4_prep -p 'test_*.py' -v  PASS (31)
python3 -m unittest discover -s tests/b5 -p 'test_*.py' -v  PASS (6)
git diff --check d8ad99a..HEAD  PASS
```

No physical-device command or service was started during validation.
