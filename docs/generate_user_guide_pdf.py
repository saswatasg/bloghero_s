"""Generate BlogHero_Windows_User_Guide.pdf - a beginner-friendly, step-by-step
manual for the BlogHero desktop app on Windows, including how to obtain every
API key and credential from scratch.

Run, from the repo root (use the project venv):
    .venv/bin/python docs/generate_user_guide_pdf.py
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent / "BlogHero_Windows_User_Guide.pdf"

base = getSampleStyleSheet()
BODY = ParagraphStyle("Body", parent=base["BodyText"], fontSize=10, leading=14.5, spaceAfter=6)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=18, bulletIndent=4, spaceAfter=3)
NUM = ParagraphStyle("Num", parent=BODY, leftIndent=24, bulletIndent=8, spaceAfter=5)
H1 = ParagraphStyle("H1", parent=base["Heading1"], fontSize=16, leading=20, spaceBefore=14,
                    spaceAfter=8, textColor=colors.HexColor("#14354f"))
H2 = ParagraphStyle("H2", parent=base["Heading2"], fontSize=12.5, leading=16, spaceBefore=10,
                    spaceAfter=5, textColor=colors.HexColor("#2a5d84"))
H3 = ParagraphStyle("H3", parent=base["Heading3"], fontSize=11, leading=14, spaceBefore=7, spaceAfter=3)
NOTE = ParagraphStyle("Note", parent=BODY, fontSize=9.5, leading=13.5,
                      backColor=colors.HexColor("#eef5fb"), borderColor=colors.HexColor("#7aa8cc"),
                      borderWidth=0.75, borderPadding=7, spaceAfter=8, leftIndent=4, rightIndent=4)
WARN = ParagraphStyle("Warn", parent=NOTE, backColor=colors.HexColor("#fdf3ec"),
                      borderColor=colors.HexColor("#cc7a52"))
GOOD = ParagraphStyle("Good", parent=NOTE, backColor=colors.HexColor("#edf7ee"),
                      borderColor=colors.HexColor("#4f9d5d"))
CODE = ParagraphStyle("Code", parent=BODY, fontName="Courier", fontSize=8.5, leading=12.5,
                      backColor=colors.HexColor("#f5f5f5"), borderColor=colors.HexColor("#cccccc"),
                      borderWidth=0.5, borderPadding=6, leftIndent=6, rightIndent=6)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8.5, leading=11, textColor=colors.grey)
TITLE = ParagraphStyle("Title", parent=base["Title"], fontSize=29, leading=33,
                       textColor=colors.HexColor("#0f2f45"))
SUBTITLE = ParagraphStyle("SubTitle", parent=BODY, fontSize=13.5, leading=18,
                          textColor=colors.HexColor("#3d6b8e"))

story = []


def h1(text):
    para = Paragraph(text, H1)
    story.append(para)
    return para


def h2(text):
    para = Paragraph(text, H2)
    story.append(para)
    return para


def h3(text):
    para = Paragraph(text, H3)
    story.append(para)
    return para


def p(text):
    story.append(Paragraph(text, BODY))


def bullets(items):
    for it in items:
        story.append(Paragraph(it, BULLET, bulletText="\u2022"))


def steps(items):
    for i, it in enumerate(items, start=1):
        story.append(Paragraph(f"{i}. {it}", NUM))


def note(text):
    story.append(Paragraph("<b>Note.</b> " + text, NOTE))


def warn(text):
    story.append(Paragraph("<b>Heads up.</b> " + text, WARN))


def good(text):
    story.append(Paragraph("<b>Good to know.</b> " + text, GOOD))


def code(text):
    story.append(Paragraph(text, CODE))


def table(data, widths=None):
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c6cacd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if data:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2ebf3")))
        style.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 8))


def spacer(h=8):
    story.append(Spacer(1, h))


def keep(*flowables):
    story.append(KeepTogether([f for f in flowables if f is not None]))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(0.9 * 72, 0.55 * 72, "BlogHero for Windows - Complete Beginner's Guide")
    canvas.drawRightString(letter[0] - 0.9 * 72, 0.55 * 72, "Page %d" % doc.page)
    canvas.restoreState()


# =============================================================================
# COVER
# =============================================================================
story.append(Spacer(1, 80))
story.append(Paragraph("BlogHero", TITLE))
story.append(Spacer(1, 12))
story.append(Paragraph("The Complete Beginner's Guide for Windows", SUBTITLE))
story.append(Spacer(1, 30))
p("Everything you need to know, in plain English: what the app does, how to "
  "install it, how to get every API key and credential step by step, how to run "
  "your first research and writing session, and how to fix the most common "
  "problems - with no coding, no jargon, and no skipped steps.")
story.append(Spacer(1, 40))
h2("This guide covers:")
bullets([
    "Installing BlogHero on Windows 10 or 11 (a single double-click; no Python needed)",
    "Getting a free Google Gemini API key (required, 3 minutes)",
    "Creating a Google service account and giving it Search Console access",
    "Getting a WordPress Application Password and setting up the review Google Sheet",
    "Walking through all 8 setup wizard steps",
    "Using the dashboard: Find new topics, Write queued posts, Run both",
    "Understanding REVIVAL, GAP, and MANUAL topics",
    "The enforced 1,200-1,500 word target for every new post and how review works",
    "Backup / moving BlogHero to another computer + full troubleshooting reference",
])
story.append(PageBreak())

# =============================================================================
# CONTENTS
# =============================================================================
h1("Contents")
toc = [
    "1. What BlogHero does (and does not do)",
    "2. What you need before you start (checklist)",
    "3. Installing the app on Windows",
    "4. The two main screens: wizard and dashboard",
    "5. Getting a Google Gemini API key (required)",
    "6. The setup wizard, all 8 steps explained",
    "7. Getting an Anthropic/Claude API key (optional)",
    "8. Creating the Google service account (JSON key) step by step",
    "9. Giving the service account Search Console access",
    "10. Getting a WordPress Application Password",
    "11. Setting up the Google Sheet review log",
    "12. Run behavior settings explained",
    "13. The main dashboard, button by button",
    "14. Your first full session, end to end",
    "15. Understanding REVIVAL, GAP and MANUAL topics",
    "16. Adding a topic manually + keyword research",
    "17. Where the files live on your PC",
    "18. The human review workflow",
    "19. Moving to another computer (export/import credentials)",
    "20. Troubleshooting common problems",
    "21. FAQ",
    "22. Quick reference card + last safety word",
]
for line in toc:
    story.append(Paragraph(line, BODY))
story.append(PageBreak())

# =============================================================================
# 1
# =============================================================================
h1("1. What BlogHero Does (and Does Not Do)")
p("BlogHero is a small desktop program that helps you run a blog the way a small "
  "SEO team would - but all by yourself. It does four jobs, in this order:")
steps([
    "Research: it reads your real Google Search Console data (the free Google tool "
    "that records every search people used to reach your site over the last 90 days) "
    "and works out which blog topics are genuinely worth writing next.",
    "Draft: for each chosen topic it first builds a detailed research brief (what to "
    "cover, which real questions to answer), then writes the post - either with "
    "Google's Gemini or Anthropic's Claude, whichever you picked.",
    "Polish and prepare: it fact-checks the draft, smooths stiff AI writing, writes "
    "the SEO title, meta description and slug, adds only verified internal links, and "
    "attaches images.",
    "Deliver for your review: it saves every post as a WordPress DRAFT (never "
    "published) and logs every submission in a Google Sheet, so a human - you - makes "
    "the final call before anything goes live.",
])
warn("This is the most important sentence of this guide: BlogHero <b>never "
     "publishes automatically</b>. It only ever creates WordPress drafts that wait for "
     "a human click. You will never find that it published something on its own.")
spacer(4)
p("Two things the app is deliberately strict about:")
bullets([
    "<b>Word count is enforced:</b> every new post must be between <b>1,200 and 1,500 "
    "words</b>. If a draft is too short or too long, the app retries automatically "
    "(up to 4 attempts for the draft itself, plus up to 3 checks during the polish "
    "pass), and only if it really cannot land in range does it save the post anyway - "
    "clearly marked <b>NEEDS REVIEW</b> for you to trim or extend by hand.",
    "<b>No invented URLs.</b> Internal links can only point to pages BlogHero has "
    "really checked to exist (sitemap + WordPress post list). If the writing model "
    "tries to add a link to some guessed URL, the app strips it out.",
])

# =============================================================================
# 2
# =============================================================================
h1("2. What You Need Before You Start (Checklist)")
p("Nothing here costs money, and you only do each step once. Tick the boxes as you go:")
keep(
    h3("Checklist"),
    table([
        ["What", "Where you get it", "Cost"],
        ["Windows 10 or Windows 11 computer", "Your own PC", "Free"],
        ["A Google account (personal is fine)", "accounts.google.com", "Free"],
        ["The BlogHero app file (BlogHero.exe)", "See section 3 (GitHub Releases)", "Free"],
        ["A Gemini API key", "aistudio.google.com/apikey (section 5)", "Free tier"],
        ["A Google service account (a downloaded .json file)", "console.cloud.google.com (section 8)", "Free"],
        ["The service account email added to Search Console", "search.google.com/search-console (section 9)", "Free"],
        ["A WordPress login and an Application Password", "Your wp-admin (section 10)", "Already yours"],
        ["A Google Sheet for the review log", "sheets.google.com (section 11)", "Free"],
    ]),
)
note("You do not need Python, a terminal, or to type any commands. You do need to "
     "be able to log into the website's WordPress admin (ask whoever manages the site "
     "if you do not have that), plus a Google account.")
p("Estimated total setup time once per machine: 25-35 minutes. Most of that is the "
  "one-time Google Cloud work in section 8.")

# =============================================================================
# 3
# =============================================================================
h1("3. Installing BlogHero on Windows")
p("The app ships, like most software, as one .exe file you just run. There is no "
  "installer popup chain - double-clicking is the whole install:")
steps([
    "Open the GitHub Releases page for BlogHero (ask the person who shared this "
    "guide, or open the repository and click the Releases tab on the right).",
    "Download the file named BlogHero.exe. (Ignore everything that says Mac on "
    "your screen if it shows a Mac file.)",
    "Go to your Downloads folder and double-click BlogHero.exe.",
    "If Windows shows a blue 'SmartScreen' window that says 'Windows protected "
    "your PC', click <b>More info</b>, then click <b>Run anyway</b>. This is normal "
    "for new apps and is not a warning about the file itself.",
    "The BlogHero window opens. The first time, it starts with the setup wizard - "
    "that is expected and correct. You will complete it over the next sections.",
])
good("BlogHero is portable in the sense that this file can be copied to a USB stick "
     "or run straight from a folder. All of its data (settings, topics, drafts) is "
     "saved automatically in your own Windows user-profile folder - never inside a "
     "random download directory and never lost when the app is updated.")

# =============================================================================
# 4
# =============================================================================
h1("4. The Two Screens: Wizard and Dashboard")
bullets([
    "<b>The Setup Wizard</b> - shown on first launch and anytime setup is incomplete. "
    "It asks about your website, keys, WordPress and Google Sheet, one step at a time. "
    "All 8 steps are explained in section 6.",
    "<b>The Dashboard</b> - the main control panel, shown once setup is complete: "
    "run buttons, a live progress log, topic list, drafts, and a few handy side "
    "buttons (keyword research, add topic manually, export credentials, edit setup).",
])

# =============================================================================
# 5
# =============================================================================
h1("5. Getting a Google Gemini API Key (The First Key)")
p("Gemini is Google's AI model. BlogHero uses it for the research step, for images, "
  "and - optionally - for writing. You need an 'API key': a long secret string that "
  "gives the app permission to use the AI on your behalf.")
steps([
    "Open a web browser and go to <b>aistudio.google.com/apikey</b>.",
    "Sign in with any Google account (a personal Gmail address is completely fine "
    "for this).",
    "Click the button <b>'Create API key'</b>.",
    "If Google asks for a Cloud project: choose 'Create new project' (or accept the "
    "default) and click 'Create API key' again.",
    "Your key, a long random string, is displayed with a Copy button. Copy it and "
    "keep it somewhere handy (a notepad file in your downloads folder is fine).",
    "In BlogHero's wizard, this key goes into the 'Gemini API key' field (step 2 of "
    "the wizard, section 6). You never type it anywhere else.",
])
note("Treat this string like a password: do not paste it into chat or public files. "
     "Google issues free tier with generous limits for personal use; if you ever "
     "exceed the limit, the app shows a clear 'quota exceeded' message - wait a "
     "couple of minutes and continue.")

# =============================================================================
# 6
# =============================================================================
h1("6. The Setup Wizard, All 8 Steps")
p("The wizard runs one screen at a time, with Next and Back buttons. Here is exactly "
  "what each step wants:")

h2("Step 1 - Your website")
bullets([
    "<b>Website domain</b>: the domain only, e.g. sierralivingconcepts.com (no https://).",
    "<b>Full website URL</b>: the full address, e.g. https://www.sierralivingconcepts.com.",
    "<b>Blog path</b>: keep /blog/ unless your blog lives somewhere else. This keeps "
    "research limited to blog pages only (product pages are never picked as topics).",
])
h2("Step 2 - Gemini API key")
p("Paste your key from section 5. Leave 'Text model' and 'Image model' as the default "
  "values - they are official current models and only need changing if Google ever "
  "renames them (the README says which setting that is).")
h2("Step 3 - Writing model")
bullets([
  "<b>Write posts with</b>: choose Gemini, or Claude if you have a Claude key (section 7).",
  "If you chose Claude, paste your Anthropic key in the field that appears.",
  "The research step always uses Gemini; this choice only controls who writes the "
  "draft, fact-checks, polish, and SEO metadata.",
])
p("You can switch this setting later; only future posts are affected.")
h2("Step 4 - Google service account (the JSON key)")
p("Section 8 explains how to create this and download the file. In the wizard, "
  "click <b>Upload the service account JSON key file</b> and choose the .json file "
  "you downloaded. BlogHero copies it into your user folder automatically.")
h2("Step 5 - Search Console access")
p("Before using the wizard button, you add the service account email in Search "
  "Console (section 9). Then on this screen click the button to load the list of "
  "properties this account can access, and pick your website from that list. The "
  "picked string - e.g. https://www.sierralivingconcepts.com/ - is what research "
  "uses.")
h2("Step 6 - WordPress (drafts only)")
bullets([
  "<b>WordPress site URL</b>: https://your-site.com",
  "<b>WordPress username</b>: the admin username that will own the drafts.",
  "<b>Application password</b>: generated in section 10 - NOT your login password. "
  "It looks like 'xxxx xxxx xxxx xxxx xxxx xxxx'.",
])
h2("Step 7 - Google Sheet (review log)")
bullets([
  "Create a small blank Sheet at sheets.google.com (section 11).",
  "Share it with the service account email and give that email Editor access.",
  "Paste the Sheet ID (the long string from the URL) into the wizard.",
])
h2("Step 8 - Run behavior")
p("The defaults write 2 posts per click, and strictly enforce 1,200-1,500 words. "
  "You can normally keep these as they are. Section 13 explains every number.")

# =============================================================================
# 7
# =============================================================================
h1("7. Getting an Anthropic Claude API Key (Optional)")
steps([
  "Open console.anthropic.com and create / sign in to an account.",
  "Go to the API Keys page (left menu), click 'Create Key'.",
  "Name it something clear like 'BlogHero', then copy the key value shown once.",
  "Paste it into the wizard's Writing model step (section 6, step 3) and choose Claude.",
])
warn("Claude's API is a paid service (it includes a refundable trial credit). "
     "Unless you specifically want Claude, the free Gemini tier is completely "
     "sufficient for this workflow.")

# =============================================================================
# 8
# =============================================================================
h1("8. Creating the Google Service Account (JSON Key), Step by Step")
p("This 'robot identity' is what lets BlogHero read Search Console and write to your "
  "Sheet. It is the only technically complex part, and you only do it once.")
steps([
  "Go to <b>console.cloud.google.com</b> and sign in (email - any Google account).",
  "Make sure a project exists: at the top of the page is a project selector. If "
  "there is no project, click the selector and then 'New Project' - give it any "
  "name that appeals to you, e.g. 'BlogHero'.",
  "Once a project is active, click the top-left menu (the three lines) and open "
  "'APIs &amp; services' for that project (in older layouts: 'Enabled APIs and services').",
  "Click '+ ENABLE APIS AND SERVICES' (or the Enable button on the page if shown).",
  "In the search box type 'Google Sheets API'. Click the result and on its page "
  "click <b>Enable</b>.",
  "Repeat for the <b>Google Search Console API</b> (it may also appear as "
  "'Webmasters API' - it is the same thing; enable it).",
  "Now create the robot: left menu > <b>IAM &amp; Admin</b> > <b>Service Accounts</b>.",
  "Click '+ Create service account', type a name like 'bloghero', leave everything "
  "else as it is and click 'Create and continue' twice, then 'Done'.",
  "In the list that appears, click on the row of your new service account to open it.",
  "Click the <b>KEYS</b> tab at the top of the account screen.",
  "Click '<b>Add key</b>' and then '<b>Create new key</b>'.",
  "The dialog will ask for a format: choose <b>JSON</b> and click <b>Create</b>.",
  "Your browser downloads a file whose name is something like "
  "<font face='Courier'>bloghero-123456-abcdef.json</font>. Save it somewhere "
  "findable (Downloads is perfect) - you will upload it in the wizard's step 4.",
  "Open the file in Notepad (right-click the file, Open with, Notepad) and find "
  "the line that starts with \"client_email\": it looks like "
  "<font face='Courier'>bloghero@your-project.iam.gserviceaccount.com</font> - "
  "that is the 'service account email'. Write it down; you need it in sections 9 and 11.",
])
note("You need the saved .json file only once (for the wizard upload in step 4). "
     "After that the file is copied into the app's own folder and never needed again.")
warn("This JSON file is a real credential with real powers. Treat it as a password. "
     "Never email it unprotected, never open it in shared/cloud storage, and delete "
     "the downloaded copy once the key is in the app. If it is ever leaked or lost, "
     "go back to Keys > make a new key in the same location and delete the old one.")

# =============================================================================
# 9
# =============================================================================
h1("9. Giving the Service Account Search Console Access")
p("Google requires one manual sharing step when connecting Search Console. It cannot "
  "be skipped by BlogHero or any tool.")
steps([
  "Go to <b>search.google.com/search-console</b> and sign in with the account that "
  "owns the website's Search Console property.",
  "At the top-left choose the right property (your website). If a property does not "
  "exist for it yet, add it first (Search Console > Add property, use the exact URL "
  "variant your site uses - e.g. https://www.sierralivingconcepts.com/ without a "
  "hash - and verify it).",
  "With the property open, click <b>Settings</b> in the left sidebar.",
  "Click <b>Users and permissions</b>.",
  "Click <b>Add user</b>.",
  "Paste the service account email (the other thing from the JSON file, section 8) "
  "into the email field.",
  "Set the permission level to <b>Restricted</b> - BlogHero only ever reads data, "
  "so this is the right level and nothing more is needed.",
  "Click <b>Add</b>. Google usually grants access quickly, but allow up to a few "
  "minutes before testing.",
])
warn("Most 'no data' reports after a run are explained by this single step. The "
     "live log in the app even prints the exact message for this case, instructing "
     "you to add the user in Settings > Users and permissions.")

# =============================================================================
# 10
# =============================================================================
h1("10. Getting a WordPress Application Password (For Blog Drafts)")
steps([
  "Log into the WordPress admin of your site (for example "
  "https://www.your-site.com/wp-admin).",
  "Go to <b>Users</b> &gt; <b>Profile</b>.",
  "Scroll near the bottom of the page to the box titled <b>Application Passwords</b>.",
  "In the 'New Application Password' field type a memorable name, e.g. 'BlogHero'.",
  "Click the dark button <b>Add New Application Password</b>.",
  "WordPress then displays a password once, spaced as four groups, e.g. "
  "<font face='Courier'>abcd efgh ijkl mnop</font> - copy it immediately (very "
  "important, it is shown only on that single moment).",
  "Paste it into the wizard's WordPress step (section 6, step 6).",
])
note("This is NOT your login password. An application password is a dedicated "
     "secret that only works over the API and can be revoked from the same page at "
     "any time without touching your normal login.")

# =============================================================================
# 11
# =============================================================================
h1("11. Setting Up the Google Sheet (Review Log)")
steps([
  "Go to sheets.google.com and click <b>Blank spreadsheet</b>.",
  "Give the file a simple name, e.g. 'BlogReviews'.",
  "Click the big green <b>Share</b> button (top right).",
  "In the 'Add people' box, paste the service account's client email (section 8).",
  "Choose <b>Editor</b> permission (the middle option) and click Share.",
  "Now find the <b>Sheet ID</b>: it is the long field in the address bar of your "
  "sheet, sitting between the /d/ and the /edit. For example, in "
  "<font face='Courier'>https://docs.google.com/spreadsheets/d/1AbC...Yz123/edit</font>, "
  "the Sheet ID is the part <font face='Courier'>1AbC...Yz123</font>.",
  "Paste that ID into the wizard (step 7). Done.",
])
note("You do not need to create any tabs inside the sheet - the app finds (or "
     "creates) a tab named 'Run Log', and appends one row per post with the date, "
     "topic, type, category, priority, a link straight to that post's WordPress "
     "edit page, the image source, the number of fact-check flags and the final "
     "word count. That row is your review queue.")

# =============================================================================
# 12
# =============================================================================
h1("12. Run Behavior Settings Explained")
table([
    ["Setting", "What it does", "Recommended"],
    ["Write-queued-posts per run", "How many queued topics BlogHero turns into "
     "drafts on one click", "2 (or 3-4 at a time)"],
    ["Minimum words per post", "Floor - the hard minimum word count every new "
     "draft must reach. The app answers retries until it does.", "1200"],
    ["Maximum words per post", "Ceiling - the hard maximum word count. Retries when over.", "1500"],
    ["Revival impression threshold", "A blog page needs at least this many Search "
     "Console impressions (90 days) to be regarded as a revival candidate.", "5000"],
    ["Gap impression threshold", "A query needs at least this many impressions to be "
     "regarded as worth a new post.", "500"],
])
note("Guaranteed as per your requirement: every post written by the app must end "
     "up inside 1,200-1,500 words. The limits are configurable - changing the numbers "
     "here changes what the app enforces. The moment a draft cannot be forced in "
     "the range after auto-retries, the app flags it with NEEDS REVIEW on the "
     "dashboard and in the file itself, so the problem can never happen silently.")

# =============================================================================
# 13
# =============================================================================
h1("13. The Dashboard, Button by Button")
p("Once setup is finished, this screen is your control panel:")
bullets([
  "<b>'Find new topics' (Step 1)</b> - pulls the last 90 days of Search Console "
  "data and adds candidates to the list below. This only builds the queue; nothing "
  "is ever written by this button.",
  "<b>'Write queued posts' (Step 2)</b> - takes the queued topics (up to the per-run "
  "limit you set) and creates finished drafts. For every post it runs the full "
  "chain: SEO research brief -> real internal-link shortlist -> draft (1,200-1,500 "
  "words, enforced with retries) -> fact-check -> humanize polish -> SEO metadata "
  "-> images embedded -> saved locally + WordPress draft link.",
  "<b>'Run both, in order'</b> - does Step 1 and then Step 2 in a single click.",
  "<b>'+ Add a topic manually'</b> - queues a topic by hand, bypassing Search "
  "Console entirely (great when you already know your next topic).",
  "<b>'Keyword research'</b> - free, on-demand ideas for a seed word: AI ideas + "
  "your own real GSC matches + Google Autocomplete + Google Trends interest score "
  "if reachable.",
  "<b>Live log</b> - the big text area at the right/bottom. Every action prints "
  "real, current details: 'Pulling GSC data...', 'Draft attempt 1: 1180 words...', "
  "'Saved local draft: ...'.",
  "<b>Backlog table</b> - all topics with type (REV/GAP/MANUAL), category, "
  "priority and status (queued / drafted).",
  "<b>Drafts list</b> - every completed post file, click to read the full text and "
  "metadata (including word count and NEEDS REVIEW status).",
  "<b>Export credentials / Edit setup</b> - details in sections 19 and 6.",
  "<b>Pause / Resume / Stop</b> - appear during a 'Write' run. They only take "
  "effect between topics: the current post finishes cleanly first, remaining "
  "topics simply stay in the queue.",
])

# =============================================================================
# 14
# =============================================================================
h1("14. Your First Session, End to End")
steps([
  "Open the WordPress admin in one tab (you may want it for the review step).",
  "In BlogHero: <b>Find new topics</b>. Watch the live log; when it shows "
  "'>>> Research complete. N new topics added' the queue is ready.",
  "If you want a must-do topic, click '+ Add a topic manually' (section 16) - it "
  "appears in the backlog immediately.",
  "Click <b>Write queued posts</b>. The log advances per topic through all the "
  "work items (research brief, links, draft word-count-gated, fact-check, humanize, "
  "metadata, images), then prints the saved WordPress-draft link.",
  "When it prints '>>> Write run complete.' it is finished.",
  "Switch to your WordPress tab and open Posts - you will see your new posts "
  "with status 'Draft'. Open each one and check with the review checklist "
  "(section 18). The Google Sheet's Run Log also has a row for each.",
])
good("The whole point of the app is that you are not trusting an AI - you are only "
     "auto-writing candidates that you then personally review for facts, tone and "
     "figures. The review is your one headquarters and the app is the free labour.")

# =============================================================================
# 15
# =============================================================================
h1("15. Understanding REVIVAL, GAP and MANUAL")
table([
    ["Type", "What it means", "What BlogHero gives you"],
    ["REVIVAL", "An existing published post gets real search impressions but a poor "
     "click rate - the title / meta / opening are almost always the cause.", "A revival "
     "`.md` file with 3 alternative titles, 3 alternative meta descriptions and a "
     "rewritten opening paragraph. You apply it (manually) to the existing post."],
    ["GAP", "A real search phrase with solid demand, where no page on the whole site "
     "ranks well yet. Nobody is properly answering it.", "A fresh outline and draft "
     "for a completely new post."],
    ["MANUAL", "You added it yourself via the button.", "A brand new post like a GAP."],
])
p("Two rules: new content (GAP/MANUAL) is always written before any REVIVAL, "
  "regardless of priority; and within a group, Critical -> High -> Medium -> Low "
  "still determines the order. The rationale: grow the library first, fix things later.")

# =============================================================================
# 16
# =============================================================================
h1("16. Adding a Topic by Hand and Keyword Research")
h2("Add a topic manually")
steps([
  "Click '+ Add a topic manually'.",
  "Type the topic in everyday words, e.g. 'How much space for a 6-seater dining "
  "table and chairs'.",
  "Choose Category and Priority from the dropdowns, then confirm.",
  "The topic appears in the backlog as MANUAL and will be picked up by the next "
  "Write run exactly like an auto-discovered topic.",
])
h2("Keyword research panel")
p("Enter any seed (e.g. 'dining table sizing') and BlogHero returns a brainstorming "
  "list from up to four honest sources:")
bullets([
  "AI-generated ideas (Gemini) with an intent label (informational / comparison / "
  "commercial / care) and a sentence of rationale.",
  "Your own real Search Console history: any real query containing the seed gets "
  "'from your search data' and, where available, its actual impressions / clicks.",
  "Google Autocomplete: the exact phrases Google suggests while typing (when reachable),",
  "Google Trends: a relative 0-100 interest score with a Rising/Steady/Falling "
  "direction badge (an informative signal, not a search volume).",
])
warn("These are ideas with real GSC data where it exists - never invented "
     "'search volume' numbers. That is deliberate: nothing free provides "
     "trustworthy absolute volumes, and the app will not fake a figure. "
     "Keyword Planner is documented in the README as the future upgrade path to "
     "real volumes.")

# =============================================================================
# 17
# =============================================================================
h1("17. Where the Files Live (Windows)")
note("On Windows everything live in %APPDATA%\\BlogHero. The easiest way to open "
     "that folder: press Win+R, type %APPDATA%\\BlogHero and press Enter.")
table([
    ["Item", "Location"],
    ["Settings and all keys", "%APPDATA%\\BlogHero\\config.env"],
    ["Google service account copy", "%APPDATA%\\BlogHero\\gsheets_service_account.json"],
    ["Topic list (backlog)", "%APPDATA%\\BlogHero\\topic_backlog.csv"],
    ["Every saved draft (markdown)", "%APPDATA%\\BlogHero\\drafts\\  (e.g. solid_oak_dining_table_maintenance.md)"],
    ["Generated images", "%APPDATA%\\BlogHero\\generated_images\\"],
    ["Blog drafts for publishing", "WordPress admin > Posts (status: Draft)"],
    ["Review list", "Your Google Sheet, tab 'Run Log'"],
])

# =============================================================================
# 18
# =============================================================================
h1("18. The Human Review Workflow")
steps([
  "After a write run, open the Google Sheet: it has one row per post with a link "
  "to its WordPress edit page.",
  "Click each link, then Open the Draft in the editor.",
  "Read the draft. Check the title / meta and the word count shown at the bottom "
  "(the goal is 1,200-1,500).",
  "If you see a [VERIFY: ...] mark or a fact-check flag (the sheet and the file "
  "show the count), look up those numbers and claims before publishing.",
  "Check that internal links point at pages that genuinely exist (they normally "
  "will - the link list is verified).",
  "When satisfied, change the status from 'Draft' to 'Publish'. Nobody else can "
  "or will do this - it is yours.",
])
warn("Any draft flagged NEEDS REVIEW - meaning the app could not steer it into "
     "the 1,200-1,500 range after all its retries - should be lengthened or trimmed "
     "by you (a few useful sentences or a short cut) before publishing. The app "
     "saves it anyway on purpose: never lose work, just mark it for the human.")

# =============================================================================
# 19
# =============================================================================
h1("19. Moving to Another PC (Export/Import Credentials)")
p("Everything BlogHero needs on a new machine - your API keys, the service "
  "account JSON, and all site settings - fits inside one exported .zip file. That "
  "means moving machines involves no re-typing of keys:")
steps([
  "On this PC, open the Dashboard and click 'Export credentials'. Choose where to "
  "save the bloghero_credentials.zip file.",
  "Take the file to the new PC (USB stick or a trusted transfer method).",
  "On the new PC, install and launch BlogHero (section 3). When the wizard screen "
  "appears - do NOT fill it in - instead click the 'Import credentials' banner at "
  "the top and pick that zip file.",
  "BlogHero fills in all of your keys immediately and jumps straight to the Dashboard.",
])
warn("The credentials zip contains your keys in plain text. Treat it exactly like "
     "a password file: keep it on a private medium, transmit it securely (encrypted "
     "or in a private channel), and delete it when you no longer need it.")

# =============================================================================
# 20
# =============================================================================
h1("20. Troubleshooting - the Common Cases")
table([
    ["Problem", "Most likely cause", "The fix"],
    ["Every Google API call (research or GSC) is a 403 error", "Service account "
     "email has not been added to the Console property", "Add it per section 9 "
     "(Restricted is enough). Wait minutes and retry."],
    ["'No data returned' from Find new topics", "Wrong Search Console property string, "
     "or blog path mismatch, or the property has less than 90 days of valid data",
     "Verify the picked property in the Search Console wizard step (section 6, step 5) "
     "and that SITE_BLOG_PATH matches your blog URL structure."],
    ["Nothings is written / 'WordPress not configured' in the log", "WordPress step "
     "not filled in, or the app password has the groups removed", "Re-enter the "
     "wizard WordPress step: keep the spaces in the application password as shown."],
    ["A draft says NEEDS REVIEW near its word count", "The model kept the post "
     "outside 1,200-1,500 in spite of the auto-retries", "Adjust the saved draft by "
     "hand (add a section or trim) to get into range, then publish. Exactly one "
     "sentence: that is the planned fail-safe."],
    ["No trend badge in keyword research", "Google Trends (unofficial feed) is "
     "rate-limited or temporarily off", "It is optional data: run keyword research "
     "again later; everything else works without it."],
    ["'A run is already in progress'", "You (or a second window) closed the first "
     "click twice at once", "Wait for the current run to finish - you can follow it "
     "in the live log. If the message lingers after the log has finished, restart "
     "the app."],
    ["Windows shows SmartScreen 'Windows protected your PC'", "Normal for a new, "
     "not-yet-whitelisted program", "Click 'More info' then 'Run anyway' (section 3). It "
     "is not a health warning."],
    ["The window feels too wide / text too small", "Dashboard uses a centered "
     "modern look", "Resize the window freely; the layout adapts."],
])
warn("If you ever need to isolate a problem: run nothing else in parallel, "
     "export credentials to keep a safe copy, and read the live log text carefully - "
     "it almost always names the failing step with an exact line like "
     "'GSC API call failed (403)'.")

# =============================================================================
# 21 FAQ
# =============================================================================
h1("21. FAQ")
bullets([
  "<b>Does BlogHero cost money?</b> The app is free. Google's tiers are free for "
  "this usage (Sheets/Search Console reading and Gemini free-tier key). Claude does "
  "cost money; use Gemini if you want everything effectively free.",
  "<b>Can it publish on its own?</b> No. Implementation prevents it: status is "
  "always 'draft' and the whole logging/REVIEW flow assumes a human click.",
  "<b>Can I lower the word count?</b> Yes - change MIN/MAX words in Run behavior "
  "(wizard, step 8 or Edit setup). The defaults 1,200-1,500 are the pinned "
  "instructions from the client, but the setting is theirs to change and BlogHero "
  "enforces whatever you set.",
  "<b>Where do drafts go?</b> Two places: %APPDATA%\\BlogHero\\drafts as readable-"
  "markdown files, and as WordPress Draft posts; plus a reference row in the Sheet.",
  "<b>What do [VERIFY: ...] markers mean?</b> The writing model flags any number "
  "it is not confident enough about. When you review, quickly verify those specific "
  "figures before it goes live.",
  "<b>Why is the word-count enforced twice?</b> Once at drafting and once at "
  "polishing. A model can drift the length while polishing, so it is measured "
  "on the actual final text - the perimetry is part of the product.",
  "<b>What if the app crashes in the middle of a write?</b> Whatever was already "
  "saved stays saved (each topic is written independently, and status updates only "
  "after the full chain for that topic); next run picks up the rest from the "
  "queue - 'errors leave nothing lost' is the design rule.",
])
# 22
h1("22. Quick Reference and Safety")
table([
    ["Item", "Value / note"],
    ["Word count per post (strict)", "1,200 - 1,500 (configurable, enforced with retries)"],
    ["Posts per run", "Default 2, change in Run behavior"],
    ["Period researched", "Search data of the last 90 days"],
    ["Revival minimum impressions", "5,000"],
    ["Gap minimum impressions", "500"],
    ["Gemini API key URL", "aistudio.google.com/apikey"],
    ["Cloud act and service accounts", "console.cloud.google.com"],
    ["Search Console (add user)", "search.google.com/search-console"],
    ["WordPress app passwords", "WP Admin > Users > Profile > Application Passwords"],
    ["Google Sheet ID", "The long string between /d/ and /edit of the sheet URL"],
    ["Data found", "%APPDATA%\\BlogHero"],
    ["Auto-publish?", "Never. Only drafts, always waiting for the human."],
])
spacer(6)
p("<b>Last words:</b> treat every secret this guide got you to create (Gemini key, "
  "Qualified key, service account JSON, credentials.zip) exactly like passwords. "
  "Keep drafts in review, publish only content you have actually checked, and let "
  "the app do the drudgery. Enjoy your new co-pilot!")

doc = SimpleDocTemplate(
    str(OUT), pagesize=letter,
    leftMargin=0.9 * 72, rightMargin=0.9 * 72,
    topMargin=0.8 * 72, bottomMargin=0.9 * 72,
    title="BlogHero for Windows - Complete Beginner's Guide",
    author="BlogHero",
)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("Wrote %s (%d bytes)" % (OUT, OUT.stat().st_size))