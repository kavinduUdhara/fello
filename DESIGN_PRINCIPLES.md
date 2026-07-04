# Fello Design Principles & Preferences

This document outlines the UX/UI design guidelines and layout preferences for the Fello platform. Always refer to this document when scaffolding new pages or components, or modifying existing ones.

---

## 1. Page Layouts & Containers

* **Flat, Cardless Page-Wide Forms:**
  * Do **NOT** wrap general forms, setup workflows, or page content in large card containers (e.g. avoiding classes like `bg-card border shadow-2xl rounded-2xl p-8` around the entire screen content).
  * Use a flat page-wide container with transparent background, using standard content boundaries like `w-full max-w-xl` or `max-w-2xl` and padding layout like `p-6 bg-muted/10` to match the `/projects/new` page.
* **No Top Navigation Bars in Onboarding Flows:**
  * For onboarding/setup sub-pages, do not include permanent top layout bars or header lines. The bottom Cancel/Continue actions handle the navigation flow.

---

## 2. Icon Visuals & Previews

* **Image Containment (`object-contain`):**
  * Never use `object-cover` for logos, badges, or custom icons where the height and width might differ. 
  * Always use `object-contain` to show the full, un-cropped visual.
* **Icon Padding:**
  * Always provide internal padding around preview images so they do not touch the borders:
    * Use `p-2` for standard previews (e.g., 64x64px boxes).
    * Use `p-1.5` or `p-0.5` for smaller avatars (e.g., 48x48px or 20x20px boxes).
* **Default Visual Placeholders:**
  * When no logo is uploaded and no initials are available, do **NOT** show a generic letter (like "O"). Instead, show a clean organization/building icon (like `Building2` or `GoOrganization`).

---

## 3. Inline Slugs

* **Inline Placement:**
  * Position URL path/slug previews inline right below the Title input field next to a small version of the organization icon, rather than using separate container blocks at the bottom of the page.
  * Formatted simply as `/{domain}/{slug}` (e.g., `/sliit-lk/my-org-unverified-123456`). Do not prefix with labels like `Path:`.

---

## 4. Spacing & Margins

* **Tight Spacing:**
  * Keep vertical form spacing tight. Avoid using excessively large gaps like `space-y-14` on general form wrappers.
  * Use compact gaps like `space-y-6` for form layout, and smaller padding (e.g. `pt-2` or `pt-3`) above action buttons.

---

## 5. Action Buttons & Icons

* **No Separating Divider Lines:**
  * Do **NOT** add a divider line (like `border-t`) separating form inputs from the bottom action buttons. Action buttons should sit cleanly on the flat page background.
* **Button Icon Minimalism:**
  * Keep setup/creation buttons clean. Avoid adding generic sparkles or action icons in submit buttons (like the "Continue" or "Create Org" button).
* **Upload Icon SVG:**
  * Include a clean SVG icon (e.g. an arrow pointing out of a tray) inside the upload button.
