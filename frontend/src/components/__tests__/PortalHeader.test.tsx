import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { PortalHeader } from "../AffiliateLayout";

function markup(path:string) {
  return renderToStaticMarkup(<MemoryRouter initialEntries={[path]}><PortalHeader name="Test Model" code="TESTCODE" codePending={false} month="2026-09" months={["2026-09","2026-08"]} onMonth={()=>undefined}/></MemoryRouter>);
}
describe("model navigation",()=>{
  it("lets Ranking use the eligible month picker",()=>{
    const html=markup("/ranking");
    expect(html).toContain('aria-label="Month"');
    expect(html).toContain('value="2026-08"');
    expect(html).not.toContain('value="2026-07"');
  });
  it("puts the calculation behind its own back header",()=>{
    const html=markup("/earnings");
    expect(html).toContain("How this adds up");
    expect(html).toContain("← Back");
    expect(html).not.toContain("Test Model");
  });
});
