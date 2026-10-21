from pathlib import Path
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / "artifacts/fixtures"
folder.mkdir(parents=True, exist_ok=True)
document = canvas.Canvas(str(folder / "evidence.pdf"))
document.drawString(60, 740, "ResearchOS evidence validation fixture")
document.drawString(60, 700, "Controlled experiment shows improved task completion.")
document.drawString(60, 660, "This is generated test material, not a published research claim.")
document.showPage()
document.drawString(60, 740, "Second page for navigation verification.")
document.save()
print("Generated project-local two-page PDF fixture")
