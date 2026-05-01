# Cost Rate CSV Format

MarkFlow reads provider cost rates from a CSV file that you import on the **Settings → AI Providers → Cost** page.

## Required columns

| Column | Type | Description |
|--------|------|-------------|
| `provider` | string | Provider name (e.g. `anthropic`, `openai`) |
| `model` | string | Model identifier (e.g. `claude-3-5-sonnet-20241022`) |
| `input_per_1m` | number | Cost in USD per 1 million input tokens |
| `output_per_1m` | number | Cost in USD per 1 million output tokens |

## Optional columns

| Column | Type | Description |
|--------|------|-------------|
| `cache_write_per_1m` | number | Cost per 1 million cache-write tokens (Anthropic prompt caching) |
| `cache_read_per_1m` | number | Cost per 1 million cache-read tokens |
| `vision_per_image` | number | Cost in USD per image processed |
| `batch_discount_pct` | number | Batch API discount percentage (e.g. `50` for 50% off) |
| `effective_date` | date | Date these rates take effect (`YYYY-MM-DD`). Omit if rates apply immediately. |

## Example

```csv
provider,model,input_per_1m,output_per_1m,cache_write_per_1m,cache_read_per_1m,effective_date
anthropic,claude-3-5-sonnet-20241022,3.00,15.00,3.75,0.30,2024-10-22
anthropic,claude-3-haiku-20240307,0.25,1.25,0.30,0.03,2024-03-07
openai,gpt-4o,2.50,10.00,,,
openai,gpt-4o-mini,0.15,0.60,,,
```

## Notes

- The file must be UTF-8 encoded. BOM is stripped automatically if present.
- Empty cells mean the column does not apply to that model — they are **not** treated as zero.
- Rates change without notice. Verify current pricing against each provider's dashboard before importing.
- To apply updated rates after importing, click **Reload rates** on the Cost page.
- Historical rates can be tracked by including `effective_date`. MarkFlow uses the most recent entry per model when computing costs.
