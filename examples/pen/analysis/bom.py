"""Material quantities from CAD solid volumes and a purchased refill mass."""
import csv
import json
from protocol import read, write, quantity as q, artifact

request, v, out = read()
assembly = json.loads(open(v["assembly"], encoding="utf-8").read())
densities = {"aluminum":v["aluminum_density"], "acetal":v["acetal_density"], "steel":v["steel_density"]}
rows=[]
for part in assembly["parts"]:
    mass = v["refill_mass"] if part["material"] == "purchased_refill" else part["volume_mm3"]*densities[part["material"]]/1000
    rows.append({"part":part["id"], "team":part["team"], "material":part["material"], "quantity":1,
                 "volume_mm3":round(part["volume_mm3"],5), "mass_g":round(mass,5), "process":part["process"]})
total=sum(row["mass_g"] for row in rows)
finished_al=sum(row["volume_mm3"] for row in rows if row["material"]=="aluminum")
raw_al=assembly["stock"]["aluminum_mm3"]
with (out/"bill_of_materials.csv").open("w",newline="",encoding="utf-8") as stream:
    writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
(out/"bill_of_materials.json").write_text(json.dumps({"parts":rows,"total_mass_g":total,"stock":assembly["stock"]},indent=2))
write(request,{"mass":q(total,"g"), "aluminum_volume":q(finished_al,"mm^3"), "raw_aluminum_mass":q(raw_al*v["aluminum_density"]/1000,"g"),
               "material_yield":q(100*finished_al/raw_al,"percent"), "bom":artifact(out/"bill_of_materials.json"),
               "bom_csv":artifact(out/"bill_of_materials.csv","text/csv")})
