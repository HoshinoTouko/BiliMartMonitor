import { Container, getContainer } from "@cloudflare/containers";
import { Hono } from "hono";

export class BiliMartMonitorContainer extends Container<Env> {
    // Port the container listens on (default: 8080)
    defaultPort = 8080;
    // Time before container sleeps due to inactivity.
    sleepAfter = "720h";
}

// Create Hono app with proper typing for Cloudflare Workers
const app = new Hono<{
    Bindings: Env;
}>();

// Route all requests directly to the container singleton
app.all("/*", async (c) => {
    const container = getContainer(c.env.BMM_CONTAINER);
    return await container.fetch(c.req.raw);
});

export default app;
