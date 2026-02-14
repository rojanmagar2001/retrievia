from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SeedDocumentFixture:
    key: str
    external_id: str
    title: str
    source_filename: str
    markdown: str


@dataclass(frozen=True, slots=True)
class SeedConversationFixture:
    key: str
    title: str
    opening_user_message: str
    opening_assistant_message: str
    default_question: str
    doc_keys: tuple[str, ...]


SEEDED_DOCS: tuple[SeedDocumentFixture, ...] = (
    SeedDocumentFixture(
        key="hr_onboarding",
        external_id="seed-hr-onboarding-playbook",
        title="HR Onboarding Playbook",
        source_filename="hr_onboarding_playbook.md",
        markdown="""# HR Onboarding Playbook

## New Hire Orientation
New hire orientation runs in three phases: pre-start, week one, and day thirty check-in.
Managers must schedule a 30-minute expectations meeting during week one.

## IT Access Checklist
- Request SSO account before start date.
- Provision email, HRIS access, and project tracker permissions.
- Enforce MFA setup within first 24 hours.

## Buddy Program
Each new hire gets a buddy for the first 45 days.
The buddy shares team norms, communication channels, and escalation paths.
""",
    ),
    SeedDocumentFixture(
        key="support_sla",
        external_id="seed-support-sla-policy",
        title="Customer Support SLA Policy",
        source_filename="support_sla_policy.md",
        markdown="""# Customer Support SLA Policy

## Severity Definitions
- P1: Critical outage impacting revenue path.
- P2: Major degradation with workaround.
- P3: Minor issue or informational request.

## Response Targets
- P1: First response within 15 minutes, updates every 30 minutes.
- P2: First response within 60 minutes, updates every 4 hours.
- P3: First response within 1 business day.

## Escalation Rules
P1 incidents trigger immediate incident commander assignment.
If unresolved in 2 hours, escalate to engineering director.
""",
    ),
    SeedDocumentFixture(
        key="security_baseline",
        external_id="seed-security-baseline",
        title="Security Baseline Standard",
        source_filename="security_baseline_standard.md",
        markdown="""# Security Baseline Standard

## Authentication
All workforce apps require SSO and MFA.
Shared accounts are prohibited except approved break-glass credentials.

## Data Handling
Production data must not be copied to local machines unless encrypted.
Logs containing personal data must be retained no longer than 30 days.

## Secrets Management
Secrets must be stored in a managed vault.
Rotating credentials every 90 days is mandatory for non-human service accounts.
""",
    ),
)


SEEDED_CONVERSATIONS: tuple[SeedConversationFixture, ...] = (
    SeedConversationFixture(
        key="onboarding",
        title="[seed] onboarding conversation",
        opening_user_message="Can you help me prepare onboarding for new hires?",
        opening_assistant_message="Yes. I can summarize orientation phases, IT access requirements, and buddy program steps from policy docs.",
        default_question="What are the onboarding phases and mandatory first-week actions?",
        doc_keys=("hr_onboarding",),
    ),
    SeedConversationFixture(
        key="support",
        title="[seed] support escalation conversation",
        opening_user_message="I need a quick SLA summary for our support team.",
        opening_assistant_message="I can provide severity definitions, response targets, and escalation requirements from the SLA policy.",
        default_question="What are the P1 and P2 response targets and escalation rules?",
        doc_keys=("support_sla",),
    ),
    SeedConversationFixture(
        key="security",
        title="[seed] security controls conversation",
        opening_user_message="Help me review mandatory security controls before launch.",
        opening_assistant_message="I can extract authentication, data handling, and secrets requirements from the baseline standard.",
        default_question="List mandatory controls for MFA, data retention, and secret rotation.",
        doc_keys=("security_baseline",),
    ),
)
