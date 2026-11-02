"""Transparent employee-level shift allocation heuristic."""
import argparse
from pathlib import Path
import pandas as pd

def _tokens(value):
    return {x.strip().lower() for x in str(value or "").split(";") if x.strip()}

def optimise_shifts(demand, employees, shift_hours=8, break_after=4, break_hours=1,
                    max_daily_hours=8, max_weekly_hours=40, min_rest_hours=11):
    required={"hour_utc","region","language","channel","required_agents"}
    staff_required={"employee_id","region","languages","channels"}
    if required-set(demand.columns): raise ValueError(f"Demand missing {sorted(required-set(demand.columns))}")
    if staff_required-set(employees.columns): raise ValueError(f"Roster missing {sorted(staff_required-set(employees.columns))}")
    d=demand.copy(); d["hour_utc"]=pd.to_datetime(d.hour_utc,utc=True)
    d["required_agents"]=pd.to_numeric(d.required_agents,errors="raise").clip(lower=0)
    d=d.sort_values("hour_utc").reset_index(drop=True)
    staff=employees.fillna("").copy()
    for col,default in [("max_daily_hours",max_daily_hours),("max_weekly_hours",max_weekly_hours)]:
        if col not in staff: staff[col]=default
    coverage={i:0 for i in d.index}; shifts=[]; used={}
    while True:
        best=None
        for _,e in staff.iterrows():
            eid=str(e.employee_id); state=used.get(eid,{"days":{},"weeks":{},"last_end":None})
            langs=_tokens(e.languages); channels=_tokens(e.channels); regions=_tokens(e.region)
            for start in d.hour_utc.drop_duplicates():
                end=start+pd.Timedelta(hours=shift_hours)
                if state["last_end"] is not None and (start-state["last_end"]).total_seconds()/3600<min_rest_hours: continue
                day=str(start.date()); week=f"{start.isocalendar().year}-{start.isocalendar().week:02d}"
                paid=shift_hours-break_hours
                if state["days"].get(day,0)+paid>min(float(e.max_daily_hours),max_daily_hours): continue
                if state["weeks"].get(week,0)+paid>min(float(e.max_weekly_hours),max_weekly_hours): continue
                avail_from=pd.to_datetime(e.get("available_from_utc",""),utc=True,errors="coerce")
                avail_to=pd.to_datetime(e.get("available_to_utc",""),utc=True,errors="coerce")
                if pd.notna(avail_from) and start<avail_from: continue
                if pd.notna(avail_to) and end>avail_to: continue
                leave_from=pd.to_datetime(e.get("leave_start_utc",""),utc=True,errors="coerce")
                leave_to=pd.to_datetime(e.get("leave_end_utc",""),utc=True,errors="coerce")
                if pd.notna(leave_from) and pd.notna(leave_to) and start<leave_to and end>leave_from: continue
                mask=(d.hour_utc>=start)&(d.hour_utc<end)&d.region.astype(str).str.lower().isin(regions)&d.language.astype(str).str.lower().isin(langs)&d.channel.astype(str).str.lower().isin(channels)
                slots=d.index[mask].tolist()
                productive=[i for i in slots if d.loc[i,"hour_utc"] != start+pd.Timedelta(hours=break_after)]
                gain=sum(max(0,float(d.loc[i,"required_agents"])-coverage[i]) for i in productive)
                if gain<=0: continue
                candidate={"gain":gain,"employee":eid,"start":start,"end":end,"productive":productive,"row":e}
                if best is None or (gain,eid,str(start))>(best["gain"],best["employee"],str(best["start"])): best=candidate
        if best is None: break
        e=best["row"]; eid=best["employee"]; start=best["start"]; end=best["end"]
        for i in best["productive"]: coverage[i]+=1
        paid=shift_hours-break_hours; day=str(start.date()); week=f"{start.isocalendar().year}-{start.isocalendar().week:02d}"
        state=used.setdefault(eid,{"days":{},"weeks":{},"last_end":None})
        state["days"][day]=state["days"].get(day,0)+paid; state["weeks"][week]=state["weeks"].get(week,0)+paid; state["last_end"]=end
        shifts.append({"employee_id":eid,"region":e.region,"languages":e.languages,"channels":e.channels,
                       "shift_start_utc":start,"shift_end_utc":end,
                       "break_start_utc":start+pd.Timedelta(hours=break_after),
                       "break_end_utc":start+pd.Timedelta(hours=break_after+break_hours),
                       "paid_hours":paid,"weekly_bucket":week})
    d["scheduled_agents"]=[coverage[i] for i in d.index]
    d["uncovered_agents"]=(d.required_agents-d.scheduled_agents).clip(lower=0)
    d["overstaffed_agents"]=(d.scheduled_agents-d.required_agents).clip(lower=0)
    return pd.DataFrame(shifts),d

def main():
    p=argparse.ArgumentParser(); p.add_argument("--demand",default="outputs/tableau_staffing_coverage.csv")
    p.add_argument("--employees",default="data/raw/employee_roster.csv"); p.add_argument("--output",default="outputs/employee_shift_schedule.csv")
    a=p.parse_args(); shifts,coverage=optimise_shifts(pd.read_csv(a.demand),pd.read_csv(a.employees))
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    shifts.to_csv(out,index=False); coverage.to_csv(out.with_name("employee_shift_coverage.csv"),index=False)
    print(f"Created {len(shifts)} shifts; {int(coverage.uncovered_agents.sum())} uncovered agent-hours.")
if __name__=="__main__": main()
