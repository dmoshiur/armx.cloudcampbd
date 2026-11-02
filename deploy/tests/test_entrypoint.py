"""Exercise the container entrypoint without requiring a Docker daemon."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.workspace = self.root / "workspace"
        (self.root / "backend").mkdir()
        for name in ("envsubst", "nginx", "alembic", "supervisord"):
            script = self.bin / name
            script.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n'
                'if [ "$1" = "upgrade" ] && [ -n "${FAIL_MIGRATION:-}" ]; then exit 7; fi\n'
                'exit 0\n'
            )
            script.chmod(0o755)
        # Use the real entrypoint with its image paths redirected to a temp tree.
        self.entrypoint = self.root / "entrypoint.sh"
        self.entrypoint.write_text(
            RUNTIME.joinpath("entrypoint.sh").read_text().replace("/app", str(self.root))
        )
        runtime = self.root / "deploy/runtime"
        runtime.mkdir(parents=True)
        runtime.joinpath("nginx.conf").write_text("listen ${PORT}; host $host;")
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "PROJECT_WORKSPACE": str(self.workspace),
            "ENV": "production",
            "JWT_SECRET": "test-only-not-a-production-credential",
            "WEB_ORIGIN": "https://armx.example",
        }
        for name in ("PORT", "CORS_ORIGINS", "RENDER_EXTERNAL_URL", "FAIL_MIGRATION"):
            self.env.pop(name, None)

    def run_entrypoint(self, **overrides):
        return subprocess.run(
            ["sh", str(self.entrypoint), "supervisord", "-n", "-c", "/app/supervisord.conf"],
            env={**self.env, **overrides},
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_starts_supervisor_after_migrations_with_default_port(self):
        result = self.run_entrypoint()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.workspace.is_dir())
        self.assertEqual(
            self.calls.read_text().splitlines(),
            [
                "$PORT",
                "-t -c /tmp/armx-nginx.conf",
                "upgrade head",
                "-n -c /app/supervisord.conf",
            ],
        )

    def test_runtime_port_is_substituted_without_erasing_nginx_variables(self):
        # The real envsubst is optional on a developer workstation; inspect the
        # template and command here, and exercise the actual binary in CI.
        template = RUNTIME.joinpath("nginx.conf").read_text()
        self.assertIn("listen ${PORT};", template)
        self.assertIn("$proxy_add_x_forwarded_for", template)
        result = self.run_entrypoint(PORT="8080")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("$PORT", self.calls.read_text())

    def test_rejects_invalid_and_reserved_ports(self):
        for port in ("abc", "0", "80", "1023", "65536", "-1", "3000", "8000", "80;touch /tmp/bad"):
            with self.subTest(port=port):
                result = self.run_entrypoint(PORT=port)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("PORT", result.stderr)
                self.assertFalse(self.calls.exists())

    def test_uses_render_public_origin_when_not_explicitly_configured(self):
        self.env.pop("WEB_ORIGIN")
        self.env["RENDER_EXTERNAL_URL"] = "https://armx.onrender.com"
        result = subprocess.run(
            ["sh", str(self.entrypoint), "sh", "-c", 'printf "%s\\n%s\\n" "$WEB_ORIGIN" "$CORS_ORIGINS"'],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["https://armx.onrender.com"] * 2)

    def test_explicit_origin_wins_and_supplies_default_cors(self):
        result = subprocess.run(
            ["sh", str(self.entrypoint), "sh", "-c", 'printf "%s\\n%s\\n" "$WEB_ORIGIN" "$CORS_ORIGINS"'],
            env={
                **self.env,
                "RENDER_EXTERNAL_URL": "https://other.example",
                "WEB_ORIGIN": "https://custom.example",
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["https://custom.example"] * 2)

    def test_explicit_cors_is_preserved(self):
        result = subprocess.run(
            ["sh", str(self.entrypoint), "sh", "-c", 'printf "%s" "$CORS_ORIGINS"'],
            env={**self.env, "CORS_ORIGINS": "https://custom.example,https://www.custom.example"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "https://custom.example,https://www.custom.example")

    def test_production_requires_jwt_secret(self):
        result = self.run_entrypoint(JWT_SECRET="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("JWT_SECRET", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_migration_failure_prevents_all_services_starting(self):
        result = self.run_entrypoint(FAIL_MIGRATION="1")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(
            self.calls.read_text().splitlines(),
            ["$PORT", "-t -c /tmp/armx-nginx.conf", "upgrade head"],
        )


if __name__ == "__main__":
    unittest.main()
