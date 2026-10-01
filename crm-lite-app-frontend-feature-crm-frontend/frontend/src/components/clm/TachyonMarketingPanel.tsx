import {
  ArrowsClockwise,
  Browser,
  ChartLineUp,
  Cloud,
  Gear,
  Sparkle,
  TestTube,
  UsersThree,
  WifiHigh,
} from "@phosphor-icons/react";
import BrandMark from "./BrandMark";

/** Copy is pulled verbatim from tachyontech.com's hero + "What we do" section
 * — this panel exists to carry the parent company's real positioning onto
 * the sign-in screen, not to invent new marketing copy. Update this file by
 * hand if that page's wording changes; there's no live sync to the external
 * site (a deliberate choice over iframing it — see conversation history). */
const SERVICES: { icon: React.ComponentType<{ className?: string }>; title: string; description: string }[] = [
  { icon: Sparkle, title: "AI & Generative AI", description: "Deploy AI that grows revenue and reduces operating cost. Copilots, machine learning, and automation with guardrails." },
  { icon: TestTube, title: "Testing Services", description: "Ship change with confidence. Automation, data validation, and rehearsed cutovers." },
  { icon: Cloud, title: "Cloud Services", description: "Lower total cost and increase release velocity with secure cloud foundations." },
  { icon: Browser, title: "Enterprise Applications", description: "Deliver SAP applications that reduce run costs and improve user experience." },
  { icon: ChartLineUp, title: "Data Analytics and BI", description: "Build a governed data backbone that powers decisions and AI." },
  { icon: ArrowsClockwise, title: "Digital Transformation", description: "Turn strategy into an executable roadmap tied to measurable value." },
  { icon: Gear, title: "Managed Services", description: "Optimize operations with IT management." },
  { icon: WifiHigh, title: "Internet of Things (IoT)", description: "Enable automation with IoT solutions." },
  { icon: UsersThree, title: "Professional IT Staffing", description: "Augment teams with skilled professionals." },
];

export default function TachyonMarketingPanel() {
  return (
    <div className="auth-marketing">
      <div className="auth-marketing-brand">
        <div className="auth-marketing-mark">
          <BrandMark fill="#ffffff" />
        </div>
        <div className="auth-marketing-brand-name">Tachyon Technologies</div>
      </div>

      <div>
        <div className="auth-marketing-eyebrow">Digital Transformation &amp; AI Solutions</div>
        <h2 className="auth-marketing-headline">
          Deploy governed AI agents that execute your enterprise workflows autonomously.
        </h2>
        <p className="auth-marketing-sub">Measured by outcomes, not seats. Launch a pilot in 5 days.</p>
      </div>

      <div>
        <div className="auth-marketing-section-title">What we do</div>
        <div className="auth-marketing-grid">
          {SERVICES.map(({ icon: ServiceIcon, title, description }) => (
            <div key={title} className="auth-marketing-item">
              <ServiceIcon />
              <div className="auth-marketing-item-title">{title}</div>
              <div className="auth-marketing-item-desc">{description}</div>
            </div>
          ))}
        </div>
      </div>

      <p className="auth-marketing-mission">
        Tachyon Technologies delivers cutting-edge digital transformation, AI and cloud services,
        powered by Tachyon Aura our Agentic Enterprise Platform, to help enterprises modernize
        operations and drive measurable innovation.
      </p>
    </div>
  );
}
