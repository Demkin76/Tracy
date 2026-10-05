const logoUrl = new URL("./assets/tracy-logo.svg", import.meta.url).href;

/** The supplied Tracy mark. The adjacent wordmark names the link. */
export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <img src={logoUrl} alt="" width="32" height="32" />
    </span>
  );
}
