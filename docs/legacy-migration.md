# Legacy Repository Coverage

Checked September 25, 2026 against the three public `quantlab_step*` repositories.

| Legacy package | Destination under `src/systematic_alpha_lab` | Python modules covered |
| --- | --- | --- |
| `quantlab_data_pipeline` | `data_pipeline` | 12 / 12 |
| `quantlab_factor_library` | `factor_research` | 65 / 65 |
| `alpha_compositor` | `alpha` | 6 / 6 |

Of the 83 original Python modules, 77 are byte-identical to their consolidated
counterparts. The six remaining modules change repository-root or config paths
to match the new layout. Every original top-level function/class name is present.
This is a source-coverage check, not comprehensive functional validation.

Legacy READMEs, standalone packaging/configuration, notebooks, and commit history
remain in the old repositories. Archiving is read-only preservation, not deletion
or a claim that those historical notebooks were rerun. The consolidated package
and its tests are the current development entry point.
