"""`cha-web`: the web app on the laptop (real data, Vertex AI) or in demo mode (synthetic)."""
from __future__ import annotations

import os

import typer

app = typer.Typer(add_completion=False, help=__doc__)


def uses_vertex() -> bool:
    """True when the GenAI client goes to Vertex AI, never a free-tier API key."""
    flag = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in ("1", "true")
    return flag and not os.environ.get("GOOGLE_API_KEY")


@app.command()
def serve(demo: bool = typer.Option(False, help="Serve the synthetic eval fixture (screenshots)."),
          port: int = typer.Option(8780, help="Port on 127.0.0.1."),
          host: str = typer.Option("127.0.0.1", help="Laptop and demo modes bind localhost only."),
          test_model: bool = typer.Option(
              False, help="Replay the script in CHA_WEB_FAKE_SCRIPT instead of Gemini (end-to-end "
                          "tests; demo mode only).")
          ) -> None:
    import uvicorn
    from health_agents import tracing

    from .app import create_app

    if host not in ("127.0.0.1", "localhost"):
        raise typer.BadParameter("laptop and demo modes bind 127.0.0.1 only")
    if test_model and not demo:
        raise typer.BadParameter("--test-model works only with --demo (synthetic data)")
    tracing.setup()
    if demo:
        model = None
        if test_model:
            from .scripted import ScriptedLlm

            script = os.environ.get("CHA_WEB_FAKE_SCRIPT")
            if not script:
                raise typer.BadParameter("set CHA_WEB_FAKE_SCRIPT to a JSON script file")
            model = ScriptedLlm.from_file(script)
        api = create_app("demo", model=model)
    else:
        from health_agents import vertex

        vertex.configure()  # real data goes to Gemini only through Vertex AI
        if not uses_vertex():
            raise typer.BadParameter("Real data goes to Gemini only through Vertex AI: unset "
                                     "GOOGLE_API_KEY and use GOOGLE_GENAI_USE_VERTEXAI=true "
                                     "(or run with --demo).")
        api = create_app("local")
    typer.echo(f"Calibrated Health Agent on http://{host}:{port}" + ("  (demo data)" if demo else ""))
    uvicorn.run(api, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
