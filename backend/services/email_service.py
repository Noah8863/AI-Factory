"""
services/email_service.py
─────────────────────────
Thin SMTP email sender for AI Factory notifications.

Required environment variables
───────────────────────────────
  SMTP_HOST      SMTP server hostname (e.g. smtp.gmail.com)
  SMTP_USER      Login username / sender address
  SMTP_PASSWORD  Login password (or app password)

Optional
────────
  SMTP_PORT      Default 587 (STARTTLS). Use 465 for SSL.
  SMTP_FROM      Display "From" address; falls back to SMTP_USER.
  SMTP_SSL       Set to "true" to use SMTP_SSL instead of STARTTLS.

Public API
──────────
  send_deployment_success(to_email, project_name, live_url, repo_url)
      Sends an HTML + plain-text deployment-success email.
      Returns True on success, False on failure (never raises).
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _smtp_config() -> dict | None:
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    if not (host and user and password):
        return None
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "from_addr": os.getenv("SMTP_FROM", user).strip() or user,
        "use_ssl": os.getenv("SMTP_SSL", "").strip().lower() == "true",
    }


def _send_raw(cfg: dict, to_email: str, subject: str, html: str, plain: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        if cfg["use_ssl"]:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15) as server:
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_addr"], [to_email], msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_addr"], [to_email], msg.as_string())
        return True
    except Exception as exc:
        logger.warning("SMTP send failed to %s: %s", to_email, exc)
        return False


def send_deployment_success(
    to_email: str,
    project_name: str,
    live_url: str,
    repo_url: str,
) -> bool:
    """
    Send a deployment-success notification email.
    Returns True on success, False if SMTP is not configured or send fails.
    """
    cfg = _smtp_config()
    if not cfg:
        logger.info(
            "Deployment success email skipped — SMTP_HOST/SMTP_USER/SMTP_PASSWORD not configured."
        )
        return False

    subject = f"🚀 Your project \"{project_name}\" is live!"

    plain = (
        f"Great news — {project_name} has been deployed successfully!\n\n"
        f"Live URL:   {live_url}\n"
        f"GitHub repo: {repo_url}\n\n"
        "— AI Factory"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Your project is live!</title>
</head>
<body style="margin:0;padding:0;background:#0f0f14;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f0f14;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#1a1a24;border:1px solid #2a2a3a;border-radius:16px;overflow:hidden;">

          <!-- Header gradient bar -->
          <tr>
            <td style="background:linear-gradient(135deg,#6366f1,#8b5cf6);height:5px;"></td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:36px 40px 28px;">

              <!-- Logo / wordmark -->
              <p style="margin:0 0 28px;font-size:13px;font-weight:700;letter-spacing:0.1em;
                         text-transform:uppercase;color:#6366f1;">AI Factory</p>

              <!-- Headline -->
              <h1 style="margin:0 0 10px;font-size:24px;font-weight:700;color:#f0f0f8;">
                Your project is live! 🚀
              </h1>
              <p style="margin:0 0 28px;font-size:15px;color:#9090b0;line-height:1.6;">
                <strong style="color:#e0e0f0;">{project_name}</strong> has been built and
                deployed successfully by your AI development team.
              </p>

              <!-- Live URL button -->
              <table cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
                <tr>
                  <td style="background:linear-gradient(135deg,#6366f1,#8b5cf6);
                              border-radius:8px;padding:1px;">
                    <a href="{live_url}"
                       style="display:inline-block;padding:13px 28px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
                              border-radius:7px;color:#fff;font-size:15px;font-weight:600;
                              text-decoration:none;">
                      View Live Site →
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Divider -->
              <hr style="border:none;border-top:1px solid #2a2a3a;margin:0 0 22px;" />

              <!-- Details grid -->
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
                <tr>
                  <td style="padding:10px 14px;background:#12121c;border-radius:8px;
                              border:1px solid #2a2a3a;vertical-align:top;">
                    <p style="margin:0 0 4px;font-size:11px;font-weight:600;color:#6366f1;
                               text-transform:uppercase;letter-spacing:0.08em;">Live URL</p>
                    <a href="{live_url}"
                       style="font-size:13px;color:#a5b4fc;word-break:break-all;
                              text-decoration:none;">{live_url}</a>
                  </td>
                </tr>
                <tr><td style="height:8px;"></td></tr>
                <tr>
                  <td style="padding:10px 14px;background:#12121c;border-radius:8px;
                              border:1px solid #2a2a3a;vertical-align:top;">
                    <p style="margin:0 0 4px;font-size:11px;font-weight:600;color:#6366f1;
                               text-transform:uppercase;letter-spacing:0.08em;">GitHub Repository</p>
                    <a href="{repo_url}"
                       style="font-size:13px;color:#a5b4fc;word-break:break-all;
                              text-decoration:none;">{repo_url}</a>
                  </td>
                </tr>
              </table>

              <p style="margin:0;font-size:13px;color:#60607a;line-height:1.6;">
                This notification was sent because a project was successfully deployed
                on your AI Factory account.
              </p>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 40px;background:#12121c;border-top:1px solid #2a2a3a;">
              <p style="margin:0;font-size:12px;color:#50506a;">
                © AI Factory · Built by your autonomous dev team
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    ok = _send_raw(cfg, to_email, subject, html, plain)
    if ok:
        logger.info("Deployment success email sent to %s for project '%s'.", to_email, project_name)
    return ok
