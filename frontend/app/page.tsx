import Link from "next/link";
import ChargeSheetForm from "@/components/ChargeSheetForm";

export default function Home() {
  return (
    <main className="page">
      <div className="page-header">
        <div>
          <span className="kicker">Docket No. AI-001</span>
          <h1>The AI Tribunal</h1>
        </div>
        <Link href="/history">Case History →</Link>
      </div>
      <p className="intro-copy">
        Submit a charge sheet. Four AI counsel will argue the case — two for
        the prosecution, two for the defense — then three AI judges will
        independently deliberate and render a verdict.
      </p>
      <ChargeSheetForm />
    </main>
  );
}
