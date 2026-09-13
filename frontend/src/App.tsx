const features = [
  { index: "01", title: "Build your roster", copy: "Choose one castaway from every commissioner-defined bucket." },
  { index: "02", title: "Follow every point", copy: "See an auditable scoring ledger and standings that update after every correction." },
  { index: "03", title: "Back a winner", copy: "Allocate virtual currency while league-wide caps keep the field competitive." }
];

export function App() {
  return (
    <main>
      <header className="site-header">
        <a className="brand" href="/" aria-label="Survivor Fantasy home">
          <span className="brand-mark">SF</span>
          <span>Survivor Fantasy</span>
        </a>
        <span className="invite-note">Private leagues · by invitation</span>
      </header>

      <section className="hero" aria-labelledby="hero-title">
        <div className="eyebrow"><span>Season 01</span><span>Field notes</span></div>
        <div className="hero-copy">
          <p className="kicker">Outwit the spreadsheet.</p>
          <h1 id="hero-title">Your tribe.<br />Your picks.<br /><em>Your season.</em></h1>
          <p className="lede">A private fantasy league built for every vote, challenge, blindside, and comeback.</p>
          <button type="button">Sign in with your invitation <span aria-hidden="true">↗</span></button>
        </div>
        <div className="torch" aria-hidden="true">
          <div className="sun" />
          <div className="flame flame-one" />
          <div className="flame flame-two" />
          <div className="stem" />
          <div className="water-line one" />
          <div className="water-line two" />
          <div className="water-line three" />
        </div>
      </section>

      <section className="feature-grid" aria-label="How the game works">
        {features.map((feature) => (
          <article key={feature.index}>
            <span>{feature.index}</span>
            <h2>{feature.title}</h2>
            <p>{feature.copy}</p>
          </article>
        ))}
      </section>
    </main>
  );
}

