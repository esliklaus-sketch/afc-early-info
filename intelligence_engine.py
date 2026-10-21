
import os
from openai import OpenAI

SYSTEM_PROMPT = """
Ti je AFC Intelligence 2.0, analist profesionist futbolli.

Qellimi yt eshte te analizosh ndeshjet duke perdorur
informacione te verifikuara, jo te japesh baste te sigurta.

RREGULLAT E ANALIZES:

1. Kontrollo mungesat dhe demtimet.
2. Dallo mungesat e reja nga ato te vjetra.
3. Analizo rikthimet dhe rendesine e lojtareve.
4. Krahaso formen dhe forcen e kundershtareve.
5. Analizo udhetimet, lodhjen dhe pushimin.
6. Merr parasysh trajnerin dhe ndryshimet taktike.
7. Analizo levizjet e kuotave kur ka te dhena.
8. Ndaj faktet nga hipotezat.
9. Mos shpik lajme, statistika ose burime.
10. Kur informacioni mungon, thuaje qarte.

Pergjigju ne shqip, me argumente dhe perfundime.
Mos e paraqit asnje bast si te sigurt.
"""

def analyze_match(question, evidence=None):
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return "Gabim: mungon OPENAI_API_KEY."

    client = OpenAI(api_key=api_key)

    evidence_text = evidence or (
        "Nuk jane dhene burime ose te dhena aktuale. "
        "Mos pretendo se ke kontrolluar lajmet e fundit."
    )

    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            instructions=SYSTEM_PROMPT,
            input=(
                f"PYETJA:\n{question}\n\n"
                f"TE DHENAT E DISPONUESHME:\n{evidence_text}"
            ),
            max_output_tokens=1200,
        )

        return response.output_text or "Nuk u krijua analize."

    except Exception as exc:
        print("AI error:", type(exc).__name__)
        return "Analiza AI deshtoi. Kontrollo konfigurimin dhe log-et."
