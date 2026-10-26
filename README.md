# ksj-a31a-flood-tokyo23

Reproducible collection of the flood inundation areas (国土数値情報 A31a, FY2025 edition) that touch
the 23 wards of Tokyo. The dataset card is generated into `data/README.md` (not tracked; the data is
published at https://huggingface.co/datasets/yuiseki/ksj-a31a-flood-tokyo23).

```
uv run python scripts/01_download.py      # source zips, ward boundaries, docs (data/raw/<date>, data/docs)
uv run python scripts/02_export_parquet.py
uv run python scripts/03_verify.py        # a second route over every polygon of every zip (about 10 minutes)
uv run python scripts/04_card.py
uv run python src/publish.py [--push]     # dry run by default
```

The source cuts the data by river manager, not by place; the choice of zips is explained in the
card. Code: MIT. Data: CC BY 4.0, see the card.
