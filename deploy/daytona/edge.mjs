// Fixed-origin HTTPS proxy. The Daytona preview credential lives only in a Worker secret.
export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);
    if (incoming.hostname !== "tracys.online") return new Response("Unknown host", { status: 421 });
    if (incoming.protocol !== "https:") {
      incoming.protocol = "https:";
      return Response.redirect(incoming.toString(), 308);
    }
    const apiPath = incoming.pathname === "/v1" || incoming.pathname.startsWith("/v1/") ||
      ["/healthz", "/readyz", "/docs", "/openapi.json"].includes(incoming.pathname) || incoming.pathname.startsWith("/docs/");
    if (apiPath && env.API_MAINTENANCE === "true") {
      return new Response("Tracy API is being migrated. Please retry shortly.", {
        status: 503, headers: { "Cache-Control": "no-store", "Retry-After": "60" },
      });
    }
    const aws = Boolean(env.AWS_ORIGIN);
    const backend = aws || (apiPath && Boolean(env.API_ORIGIN));
    const originToken = aws ? env.AWS_ORIGIN_TOKEN : env.API_ORIGIN_TOKEN;
    let origin;
    try {
      origin = new URL(aws ? env.AWS_ORIGIN : backend ? env.API_ORIGIN : env.DAYTONA_ORIGIN);
      if (origin.protocol !== "https:" || origin.username || origin.password || origin.port ||
          origin.pathname !== "/" || origin.search || origin.hash) throw new Error("Invalid configuration");
      if (backend) {
        if (origin.hostname !== (aws ? "aws-origin.tracys.online" : "api-origin.tracys.online") || !originToken || originToken.length < 32)
          throw new Error("Invalid backend configuration");
      } else if (!/^8000-[a-z0-9-]+\.(?:proxy\.daytona\.works?|daytonaproxy01\.eu)$/.test(origin.hostname) ||
          !env.DAYTONA_PREVIEW_TOKEN) throw new Error("Invalid configuration");
    } catch {
      return new Response("Tracy deployment is not configured", { status: 503 });
    }
    // Assign pathname instead of resolving it: //host/path must never change the destination.
    const target = new URL(origin);
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    const headers = new Headers(request.headers);
    for (const name of [...headers.keys()]) {
      if (name.startsWith("x-daytona-") || name.startsWith("x-forwarded-") ||
          ["forwarded", "host", "x-tracy-origin-token"].includes(name)) headers.delete(name);
    }
    if (backend) {
      headers.set("X-Tracy-Origin-Token", originToken);
    } else {
      headers.set("X-Daytona-Preview-Token", env.DAYTONA_PREVIEW_TOKEN);
      headers.set("X-Daytona-Skip-Preview-Warning", "true");
      headers.set("X-Daytona-Disable-CORS", "true");
      headers.set("X-Daytona-Trust-Forwarded-Host", "true");
    }
    headers.set("X-Forwarded-Host", "tracys.online");
    headers.set("X-Forwarded-Proto", "https");
    try {
      const upstream = await fetch(target, {
        method: request.method, headers, redirect: "manual",
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      });
      const responseHeaders = new Headers(upstream.headers);
      for (const name of [...responseHeaders.keys()]) {
        if (name.startsWith("x-daytona-") || name === "x-tracy-origin-token") responseHeaders.delete(name);
      }
      const location = responseHeaders.get("location");
      if (location) {
        const redirect = new URL(location, origin);
        if (redirect.origin === origin.origin) {
          redirect.hostname = "tracys.online";
          responseHeaders.set("location", redirect.toString());
        }
      }
      // Account responses must never be cached by the edge.
      responseHeaders.set("Cache-Control", "no-store");
      responseHeaders.set("Strict-Transport-Security", "max-age=86400");
      responseHeaders.set("X-Content-Type-Options", "nosniff");
      return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
    } catch {
      return new Response("Tracy is temporarily unavailable", {
        status: 503, headers: { "Cache-Control": "no-store", "Retry-After": "30" },
      });
    }
  },
};
