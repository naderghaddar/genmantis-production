import LeadScraper from './components/LeadScraper';
import AgentChat from './components/AgentChat';

export default function App() {
  return <div className="app-shell">
    <header className="brand"><span className="brand-mark" aria-hidden="true">G</span>GenMantis</header>
    <main><AgentChat /><details className="manual-search"><summary>Prefer the three-field form? Open manual search</summary><LeadScraper /></details></main>
    <footer>GenMantis <span>Simple searches. Useful connections.</span></footer>
  </div>;
}
