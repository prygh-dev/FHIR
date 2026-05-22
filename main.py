import httpx
import json
from collections import defaultdict
import os

import dbm
from tqdm import tqdm

from fhir.resources.observation import Observation
from src.observation import get_observation_overview, extract_period

# TODO bundles.json already exists. Do you want to re-run the program or skip to data processing?
# print "type 'y' to skip to data processing, 'n' to re-download"

BASE = "https://hapi.fhir.org/baseR4/Patient"
DATA_DIR = "data/"

# TODO explain params
params = {
    "_count": "10",
    "_revinclude": "Observation:subject",
    "_has:Observation:subject:code": "http://loinc.org|85354-9",
}

# list of bundles. Each bundle contains Blood Pressure info for up to 10 patients
# as determined by the _count parameter.
bundles_httpx = []

if os.path.exists(DATA_DIR + "bundles.json"):
    with open(DATA_DIR + "bundles.json", "r") as f:
        bundles_httpx = json.load(f)

else:
    with httpx.Client(timeout=30) as client:
        url, query = BASE, params  # query can be a dict or None

        while url:
            request = client.build_request("GET", url, params=query)
            print("GET", request.url)

            bundle = client.send(request).raise_for_status().json()
            bundles_httpx.append(bundle)

            next_link = next(
                (l["url"] for l in bundle.get("link", []) if l["relation"] == "next"),
                None,
            )
            url, query = next_link, None  # next links are already fully qualified. Meaning that the parameters are baked into the url string

    with open(DATA_DIR + "bundles.json", "w") as f:
        json.dump(bundles_httpx, f, indent=2)

# add new bundles to db

# JSON downloaded. Now,
# print_json(data=bundles_httpx[0], default=str)

total_entries = sum(len(bundle.get("entry", [])) for bundle in bundles_httpx)
with ( dbm.open("patient_lookup.db", "c") as db1,
       dbm.open("observation_lookup.db", "c") as db2,
       dbm.open("patient_meta.db", "c") as db3,
       tqdm(total=total_entries, desc="Parsing FHIR Resources", unit="res") as pbar
    ):
    print("constructing db files")

    new_obs_accumulator = defaultdict(list)
    for bundle in bundles_httpx:
        for entry in bundle["entry"]:
            pbar.update(1)

            resource = entry["resource"]
            r_id = resource['id']
            rt = resource["resourceType"]

            if rt == 'Observation':
                if r_id in db2:
                    continue

                # codings = resource.get("code", {}).get("coding", [])
                # is_bp = any( c.get("code") == "85354-9" and c.get("system") == "http://loinc.org" for c in codings )
                # if not is_bp:
                # continue
                db2[r_id] = json.dumps(resource)

                # now link to patient via patient_meta.db
                patient_ref = resource.get("subject", {}).get("reference", "")
                patient_id = patient_ref.split("/")[-1] if "/" in patient_ref else patient_ref

                if patient_id:
                    new_obs_accumulator[patient_id].append(r_id)

            elif rt == 'Patient':
                if r_id in db1:
                    continue
                db1[r_id] = json.dumps(resource)
                if not r_id in db3:
                    # add to db3 with empty observation list
                    db3[r_id] = json.dumps([])

    # LOOP IS DONE: Now flush all accumulated patient observations to db3 at once
    print("\nFlushing new observations to disk...")
    for patient_id, new_obs_ids in new_obs_accumulator.items():
        if patient_id in db3:
            # Read and parse exactly ONCE per patient total
            existing_obs = json.loads(db3[patient_id].decode("utf-8"))
            existing_obs.extend(new_obs_ids)
            db3[patient_id] = json.dumps(existing_obs)
        else:
            db3[patient_id] = json.dumps(new_obs_ids)

    print("done constructing db files")




def get_patient_name(patient_resource):
    names = patient_resource.get("name", [])
    if not names:
        return "Anonymous or Unnamed patient"
    for name in names:
        if name.get('use') in ['official', 'usual']:
            return f"{' '.join(name.get('given', []))} {name.get('family', '')}".strip()
    fallback = names[0]
    return f"{' '.join(fallback.get('given', []))} {fallback.get('family', '')}".strip()




with dbm.open("patient_lookup.db", "r") as db1, dbm.open("observation_lookup.db", "r") as db2, dbm.open(
        "patient_meta.db", "r") as db3:
    # Show counts of each resource type
    print(f"# of patients with BP observations: {len(db1)}")
    print(f"total # of observations: {len(db2)}")

    # display patient meta-data
    i = 1
    for key in db3:  # iterate over patients
        patient_id = key.decode("utf-8")  # get patient id
        observation_id_list = json.loads(db3[key].decode("utf-8"))  # get observation id list
        # now grab patient profile
        patient_resource = json.loads(db1[patient_id].decode("utf-8"))
        patient_name = get_patient_name(patient_resource)
        output_str = str(i) + ': ' + patient_id + ', ' + patient_name + ', ' + str(len(observation_id_list))
        # print patient overview
        print(output_str)
        i = i + 1

    selected_id_list = input("Which patients would you like to analyze? ").split(' ')
    for p_id in selected_id_list:
        if p_id in db1:
            patient_resource = json.loads(db1[p_id].decode("utf-8"))
            print(f"{get_patient_name(patient_resource)}")
            observation_id_list = json.loads(db3[p_id].decode("utf-8"))  # get observation id list

            observations = []
            for o_id in observation_id_list:
                # grab observation resource by id
                #TODO surround this line with a try/catch. Error implies invalid json format for observation resource type
                observation_resource = json.loads(db2[o_id].decode("utf-8"))
                o_period = extract_period(observation_resource)
                if o_period:
                    observations.append( (observation_resource, o_period) )
                else:
                    #TODO: notify that effective time period could not be found for observation
                    pass

            observations.sort(key=lambda p: p[1][0])
            for o, period in observations:
                # get rough observation info
                print("begin observation")
                component_summary = get_observation_overview(o)
                # print
                print(f"{period[0].strftime("%m/%d/%y %H:%M:%S (%Z)")}{(' - ' + period[1].strftime("%m/%d/%y %H:%M:%S (%Z)")) if period[0] != period[1] else ''}: {component_summary}")
                print("end")

        else:
            print(f"could not find patient with id {p_id}. Skipping...")


