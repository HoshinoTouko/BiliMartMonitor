import { APP_COPYRIGHT, APP_VERSION } from "@/lib/appInfo";

export default function AppFooter() {
    return (
        <footer className="bsm-footer">
            <div className="bsm-footer-inner">v{APP_VERSION} | {APP_COPYRIGHT}</div>
        </footer>
    );
}
