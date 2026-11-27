"""Generate sample dispatch exports into exports/ (offline, deterministic, no LLM calls)."""
import sys
from pathlib import Path

from src import operations as op
from src.inference import Engine

ROOT = Path(__file__).parent
BRIEF_WARDS = ("CCC_Ward_03", "DNCC_Ward_01")


def main(scenario="peak", stock=60, crews=40, surge=1.5):
    e = Engine(ROOT / "artifacts", scenario)
    dates = {str(h): d for h, d in e.target_dates().items()}
    p = op.plan(e.wards, e.forecast_df(), int(stock), int(crews), "expected", float(surge), dates)
    out = ROOT / "exports"
    out.mkdir(exist_ok=True)
    wards = p["wards"]  # already in priority order
    (out / "sms_alerts.txt").write_text("\n".join(op.sms(r) for r in wards) + "\n", encoding="utf-8")
    pick = [r for r in wards if r["rank"] <= 10 or r["ward_id"] in BRIEF_WARDS]
    head = (f"# WhatsApp dispatch briefs\nOrigin {e.as_of}; stock {stock}%, crews {crews}, surge {surge}x; "
            f"top 10 priority wards plus {', '.join(BRIEF_WARDS)}\n\n")
    (out / "whatsapp_dispatch.md").write_text(head + "\n\n---\n\n".join(op.whatsapp(r, dates) for r in pick) + "\n", encoding="utf-8")
    for r in wards:
        if r["ward_id"] in BRIEF_WARDS:
            (out / f"commissioner_brief_{r['ward_id']}.html").write_text(op.commissioner_html(r, dates), encoding="utf-8")
    print("wrote", ", ".join(sorted(x.name for x in out.iterdir())))


if __name__ == "__main__":
    main(*sys.argv[1:])
