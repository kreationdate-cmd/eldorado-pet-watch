# eldorado-pet-watch

Hourly price watch for Tap Simulator REBORN pets on Eldorado.gg.

- `scraper.py` runs on GitHub Actions every hour at :05 (UTC). It reads Eldorado's
  public listings API (logged out, one request every 2 seconds, about 20 requests per run),
  groups listings by pet + variant using `pets.txt`, and flags anything 30% or more
  below the median of the other listings for the same pet + variant.
- Results go in `data/`. A Claude scheduled task reads them at :20 and pushes
  deals to Charles's phone. Its prompt is in `CLAUDE_TASK_PROMPT.md`.

## Setup

1. Create a **public** repo named `eldorado-pet-watch` on GitHub and upload every file
   here, keeping the `.github/workflows/` folder path.
2. Repo **Settings > Actions > General > Workflow permissions**: pick
   "Read and write permissions" and save.
3. **Actions** tab > "Scrape Eldorado" > **Run workflow** to test it once.
   A green check and a new `data/` folder mean it works.
4. In `CLAUDE_TASK_PROMPT.md`, replace `<USERNAME>` with your GitHub username.

## Checking it works

`python verify.py https://github.com/<USERNAME>/eldorado-pet-watch`
prints PASS / WARN / FAIL for: files in place, workflow ran and pushed, last run
age, hourly schedule gaps, last run errors (including Eldorado blocks), listing
counts, pet matching, and deal math. Claude runs this for you; you only need
the repo URL.

## Changing things

- Threshold: `DEAL_THRESHOLD` in `scraper.py` (0.30 = 30%).
- Missing pets: add the name to `pets.txt`.
- Stop it: Actions tab > "Scrape Eldorado" > "..." > Disable workflow.

## Limits

- If Eldorado blocks GitHub's servers, `data/status.json` shows the error and the
  Actions run turns red. The script does not try to get around blocks.
- GitHub can pause scheduled workflows in repos it considers inactive for 60 days.
  If the hourly runs stop, re-enable the workflow in the Actions tab.
- Scheduled runs can start a few minutes late when GitHub is busy.
