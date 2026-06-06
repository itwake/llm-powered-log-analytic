import { Shell } from "@/components/Shell";
import { graph } from "@/lib/fixtures";

export default function CausalGraphPage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Causal Graph</h1>
        <label>Min confidence <input type="range" min="0" max="1" step="0.1" defaultValue="0.4" /></label>
      </div>
      <section className="grid two">
        <div className="panel graph">
          <div className="node root" style={{left: 20, top: 40}}>{graph.nodes[0].label}<br /><span className="muted">rank {graph.nodes[0].rank_score}</span></div>
          <div className="edge" style={{left: 260, top: 86}}>candidate cause {"->"}</div>
          <div className="node" style={{left: 390, top: 130}}>{graph.nodes[1].label}<br /><span className="muted">rank {graph.nodes[1].rank_score}</span></div>
          <div className="edge" style={{left: 520, top: 260}}>candidate cause {"->"}</div>
          <div className="node" style={{left: 650, top: 300}}>{graph.nodes[2].label}<br /><span className="muted">rank {graph.nodes[2].rank_score}</span></div>
        </div>
        <div className="panel">
          <h2>Root Cause Candidates</h2>
          <ol>
            {graph.nodes.map(node => <li key={node.id}>{node.label} ({node.rank_score})</li>)}
          </ol>
          <h2>Edges</h2>
          {graph.edges.map(edge => (
            <p key={`${edge.source}-${edge.target}`}>{edge.source} {"->"} {edge.target}: confidence {edge.confidence}, needs validation {String(edge.needs_validation)}</p>
          ))}
        </div>
      </section>
    </Shell>
  );
}
