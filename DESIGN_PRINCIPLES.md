# Fello Design Principles & Preferences

This document outlines the UX/UI design guidelines and layout preferences for the Fello platform. Refer to this document when scaffolding new pages or components, or modifying existing ones.

---

## 1. Page Layouts & Containers

* **Flat, Cardless Page-Wide Forms:**
  * Do **NOT** wrap general forms, setup workflows, or page content in large card containers (e.g., avoiding classes like `bg-card border shadow-2xl rounded-2xl p-8` around the entire screen content).
  * Use a flat page-wide container with a transparent background, using standard content boundaries like `w-full max-w-xl` or `max-w-2xl` and padding layout like `p-6 bg-muted/10` to match the `/projects/new` page.
* **No Top Navigation Bars in Onboarding Flows:**
  * For onboarding/setup sub-pages, do not include permanent top layout bars or header lines. The bottom Cancel/Continue actions handle the navigation flow.

---

## 2. Icon Visuals, Badges & Previews

* **Image Containment (`object-contain`):**
  * Never use `object-cover` for logos, badges, or custom icons where the height and width might differ. 
  * Always use `object-contain` to show the full, un-cropped visual.
* **Icon Padding:**
  * Always provide internal padding around preview images so they do not touch the boundaries:
    * Use `p-1.5` for organization logos/avatars inside standard icon holders (e.g., `size-12` or `size-10` containers) to prevent clipping while maintaining size.
    * Use `p-2` for standard previews (e.g., `64x64px` boxes).
* **Default Visual Placeholders:**
  * When no logo is uploaded and no initials are available, do **NOT** show a generic letter (like "O"). Instead, show a clean organization/building icon (like `Building2` or `GoOrganization`).
* **Unverified Status Badge:**
  * Place the unverified badge absolutely at the top-right corner of the organization info header card (`absolute -top-2 right-4`).
  * Style the badge cleanly using neutral yellow values (`bg-yellow-500 text-white px-2 py-0.5 rounded-full text-[8px] font-bold uppercase tracking-wider`).

---

## 3. Inline Slugs

* **Inline Placement:**
  * Position URL path/slug previews inline right below the Title input field next to a small version of the organization icon, rather than using separate container blocks at the bottom of the page.
  * Formatted simply as `/{domain}/{slug}` (e.g., `/sliit-lk/my-org-unverified-123456`). Do not prefix with labels like `Path:`.

---

## 4. Spacing & Margins

* **Tight Spacing:**
  * Keep vertical form spacing tight. Avoid using excessively large gaps like `space-y-14` on general form wrappers.
  * Use compact gaps like `space-y-6` for form layouts, and smaller padding (e.g. `pt-2` or `pt-3`) above action buttons.
* **Organization Card Separation:**
  * In setup steps, add extra top padding (`pt-4`) above the title and main content blocks to create a clean separation from the organization info card on top.

---

## 5. Action Buttons & Navigation

* **Two-Button Layout (No Cancel Button):**
  * Setup/wizard flows should not have a separate `Cancel` button. Instead, provide a simple two-button footer layout:
    * **Left Button:** Represents `"I'll do it later"` (or `"Finish Setup"`) styled as a **`secondary` variant** (using neutral background/foreground secondary colors).
    * **Right Button:** Represents `"Continue"` (or `"Complete Flow"`, `"Enter Dashboard"`) styled as a **`default` (primary) variant**.
* **Button Labels:**
  * Use the exact string expression `{"I'll do it later"}` for skip buttons. Do not use unescaped string symbols or `(Skip)` text additions.
* **No Separating Divider Lines:**
  * Do **NOT** add a divider line (like `border-t`) separating form inputs from the bottom action buttons. Action buttons should sit cleanly on the flat page background.
* **Button Icon Minimalism:**
  * Keep setup/creation buttons clean. Avoid adding generic sparkles or action icons in submit buttons (like the "Continue" or "Create Org" button).
* **Upload Icon SVG:**
  * Include a clean SVG icon (e.g. an arrow pointing out of a tray) inside the upload button.

---

## 6. Realistic Loading Skeletons

* **No Fullscreen Loading Spinners:**
  * Do **NOT** use fullscreen loading spinners or simple loading indicators (like "Verifying session...") on setup or new organization pages.
* **Layout-Specific Skeletons:**
  * Always implement realistic skeleton loaders that match the layout structure of the destination page using Tailwind's pulse animation (`animate-pulse`).
  * Include placeholder skeletons for organization cards, inputs, alerts, lists, and bottom button positions.

---

## 7. Organization List Border Radii

* **Position-based Rounding:**
  * For lists (like the organization selector on the home page), the inner icon holder's border radius should match the parent list item's rounding.
  * Icon holders should round the left corners only (`group-first/row:rounded-tl-2xl` and `group-last/row:rounded-bl-2xl`), without forcing `rounded-full` on single-child elements.

---

## 8. Integration & Feature Layouts

* **Google Drive Setup (Settings Style):**
  * Include a neutral informational alert regarding indexing:
    `"Once selected, this root folder cannot be changed. If you connect an existing folder, Fello will index all its existing files automatically so you don't have to upload them again."`
  * Provide two outline buttons side-by-side: `Select a folder` and `Add a new folder`.
  * Render a clean connected card with a `Reset` action button once a folder is selected or created.
* **WhatsApp Pairing Screen:**
  * Use a native, high-fidelity inline SVG icon for WhatsApp instead of generic phone icons.
  * Warning alert blocks (such as the warning to not pair personal WhatsApp accounts) must use color-neutral styling (`bg-muted/10 border-border text-muted-foreground`) to remain professional and clean.
