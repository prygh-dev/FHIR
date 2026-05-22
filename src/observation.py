from datetime import datetime, timedelta, timezone
from fhir.resources.observation import Observation

def fhir_dt(s: str) -> datetime:
    if len(s) == 4:                                          # "2024"
        return datetime(int(s), 1, 1, tzinfo=timezone.utc)
    if len(s) == 7:                                          # "2024-03"
        return datetime.strptime(s, "%Y-%m").replace(tzinfo=timezone.utc)
    if len(s) == 10:                                         # "2024-03-15"
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))    # full form
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def format_quantity(qty_dict: dict) -> str:
    # 1. Safely grab the numeric value (could be an int or float, or None)
    val = qty_dict.get("value")

    # 2. Grab the unit text (e.g., "mg/dL"). If "unit" is missing,
    # fall back to the UCUM code string. If both missing, use empty string.
    unit = qty_dict.get("unit", qty_dict.get("code", ""))

    # 3. If there is a number, stitch them together. Otherwise, return "No Data"
    return f"{val} {unit}".strip() if val is not None else "No Data"


def extract_period(obs: dict) -> tuple[datetime, datetime] | None:
    if s := obs.get("effectiveDateTime"):
        dt = fhir_dt(s)
        return dt, dt
    if s := obs.get("effectiveInstant"):
        dt = fhir_dt(s)
        return dt, dt
    if p := obs.get("effectivePeriod"):
        start_s, end_s = p.get("start"), p.get("end")
        if not start_s and not end_s:
            return None
        start = fhir_dt(start_s) if start_s else fhir_dt(end_s)
        end   = fhir_dt(end_s)   if end_s   else start
        return start, end
    if (t := obs.get("effectiveTiming")) and (events := t.get("event")):
        parsed = [fhir_dt(e) for e in events]
        return min(parsed), max(parsed)
    return None



def observation_description(obs: dict) -> str:
    code = obs.get("code") or {}

    # 1. Free-text label, if the system provided one
    if text := code.get("text"):
        return text

    # 2. Display name from any coding (LOINC, SNOMED, etc.)
    for coding in code.get("coding", []):
        if display := coding.get("display"):
            return display

    # 3. Raw code as last resort
    for coding in code.get("coding", []):
        if c := coding.get("code"):
            sys = coding.get("system", "")
            return f"{c} ({sys})" if sys else c

    return "(no code)"


def get_observation_overview(observation_resource):
    '''
    returns date_str
    '''


    '''
    codings = observation_resource.get('code',{}).get('coding',[])
    is_bp = any( c.get("code") == "85354-9" and c.get("system") == "http://loinc.org" for c in codings )
    if not is_bp:

        else:
            observation_type = 'unknown'
    '''

    # 3. Structural Routing: Multi-Value Panel vs. Single-Value Metric
    components = observation_resource.get("component", [])
    if components:
        # Scenario A: Multi-Value Component Structure (e.g., Blood Pressure Panels)
        lines = []
        for comp in components:
            comp_codings = comp.get("code", {}).get("coding", [])
            comp_name = comp_codings[0].get("display", "Sub-component") if comp_codings else "Sub-component"

            if "valueQuantity" in comp:
                comp_value = format_quantity(comp.get("valueQuantity", {}))
            elif "valueCodeableConcept" in comp:
                comp_value = comp.get("valueCodeableConcept", {}).get("text", "Codified Value")
            else:
                comp_value = "Complex Value Type"

            lines.append(f"  - {comp_name}: {comp_value}")

        value_summary = "Measurements:\n" + "\n".join(lines)
    else:
        desc = observation_description(observation_resource)

        # Scenario B: Flat Single-Value Structure (e.g., Weight, Blood Sugar, Heart Rate)
        if "valueQuantity" in observation_resource:
            value_summary = f"{desc}: {format_quantity(observation_resource.get('valueQuantity', {}))}"
        elif "valueCodeableConcept" in observation_resource:
            value_summary = f"{desc}: {observation_resource.get('valueCodeableConcept', {}).get('text', 'Codified Value')}"
        elif "valueString" in observation_resource:
            value_summary = f"{desc}: {observation_resource.get('valueString')}"
        elif "valueBoolean" in observation_resource:
            value_summary = f"{desc}: {observation_resource.get('valueBoolean')}"
        else:
            value_summary = f"{desc}: No primary value found (check extensions or narrative)"

    return value_summary
