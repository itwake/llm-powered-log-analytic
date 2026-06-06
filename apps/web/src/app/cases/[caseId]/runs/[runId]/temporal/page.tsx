import { Shell } from "@/components/Shell";
import { temporalSeries } from "@/lib/fixtures";

export default function TemporalPage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Temporal View</h1>
        <select><option>1 minute</option><option>5 minutes</option></select>
        <select><option>Golden signal</option><option>Service</option><option>Template</option></select>
      </div>
      <section className="panel">
        <div className="grid three">
          {temporalSeries.map(series => (
            <div key={series.name}>
              <h3>{series.name}</h3>
              {series.points.map(point => (
                <div key={`${series.name}-${point.window_start}`} style={{marginBottom: 8}}>
                  <span className="muted">{point.window_start}</span>
                  <div style={{background: "#dbe5ea", height: 24, borderRadius: 4}}>
                    <div style={{background: "#285c7f", width: `${point.count * 30}%`, height: 24, borderRadius: 4}} />
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
    </Shell>
  );
}
