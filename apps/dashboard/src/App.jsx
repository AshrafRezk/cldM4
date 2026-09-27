import { useCallback, useEffect, useState } from "react";
import { Console } from "./Console.jsx";
import { haptic } from "./haptic.js";
import { Landing } from "./Landing.jsx";

function currentPath() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  return path;
}

export default function App() {
  const [path, setPath] = useState(currentPath);

  useEffect(() => {
    const onPop = () => setPath(currentPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((to) => {
    const next = to.replace(/\/+$/, "") || "/";
    haptic("tap");
    if (window.location.pathname !== next) {
      window.history.pushState({}, "", next);
    }
    setPath(next);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, []);

  const isConsole = path === "/console" || path.startsWith("/console/");

  return (
    <div className="viewport">
      <div className="atmosphere" aria-hidden="true">
        <span className="blob a" />
        <span className="blob b" />
        <span className="grain" />
      </div>
      {isConsole ? <Console go={go} path={path} /> : <Landing go={go} path={path} />}
    </div>
  );
}
