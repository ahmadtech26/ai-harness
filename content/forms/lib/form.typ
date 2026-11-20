// Shared helpers of the court and notary forms (spec .hq/docs/specs/2026-11-17-court-forms-spec.md).
// Compile from content/forms as the root:  typst compile --root content/forms --font-path <fonts> \
//   --input data=/samples/jo/<id>.json content/forms/jo/<id>.typ out.pdf
// The values arrive as JSON strings and are printed as text: a `#`, `[` or `]` a user typed prints as written.
// An empty field prints the form's dotted line, so the page can still be filled by hand.

#let data = json(sys.inputs.at("data", default: "/samples/empty.json"))

/// The value of a field, or none when it is empty.
#let val(id) = {
  let v = data.at(id, default: none)
  if v == none or v == "" or v == () { none } else { v }
}
#let has(id) = val(id) != none

/// A dotted line of the given width (a length, a ratio or `1fr`).
#let dots(width) = box(width: width, repeat(text(fill: luma(90))[.]))

/// A value as printed: a date (YYYY-MM-DD) as DD/MM/YYYY, and a value without Arabic letters (a phone, a number)
/// in a left-to-right isolate (U+2066 … U+2069), so the bidi algorithm keeps its spaced groups in order while the
/// line stays right to left.
#let shown(v) = {
  let date = v.match(regex("^(\d{4})-(\d{2})-(\d{2})$"))
  let v = if date != none { date.captures.rev().join("/") } else { v }
  if v.match(regex("\p{Arabic}")) == none { "\u{2066}" + v + "\u{2069}" } else { v }
}

/// A one-line field: its value, or a dotted line.
#let fill(id, width: 1fr) = {
  let v = val(id)
  if v == none { dots(width) } else { box(width: width, shown(v)) }
}

/// The national number in ten boxes, digits left to right as numbers are written.
#let nn(id) = {
  let v = val(id)
  let digits = if v == none { () } else { v.clusters() }
  box(baseline: 20%, {
    set text(dir: ltr)
    grid(
      columns: 10,
      ..range(10).map(i => box(
        width: 1.15em,
        height: 1.35em,
        stroke: 0.6pt,
        align(center + horizon, digits.at(i, default: "")),
      )),
    )
  })
}

/// A paragraph field: its text, or `lines` dotted lines.
#let para(id, lines: 3) = {
  let v = val(id)
  if v == none {
    for _ in range(lines) { block(spacing: 0.55em, dots(100%)) }
  } else {
    block(width: 100%, v)
  }
}

/// A list field: one line per item; when empty, `count` dotted lines.
#let items(id, count: 6, mark: [–]) = {
  let rows = val(id)
  if rows == none {
    for _ in range(count) { block(spacing: 0.55em)[#mark #h(0.4em) #dots(1fr)] }
  } else {
    for row in rows { block(spacing: 0.55em)[#mark #h(0.4em) #row] }
  }
}

/// A box ticked when the field holds `option`.
#let chosen(id, option) = box(
  baseline: 15%,
  width: 0.9em,
  height: 0.9em,
  stroke: 0.6pt,
  align(center + horizon, if val(id) == option { text(font: "DejaVu Sans Mono", size: 0.8em)[✓] }),
)

/// The page, the type and the title box shared by every form.
#let form(title, body) = {
  set page(paper: "a4", margin: (x: 2.2cm, top: 1.7cm, bottom: 1.6cm))
  set text(font: "Noto Naskh Arabic", size: 12.5pt, lang: "ar", dir: rtl)
  set par(leading: 0.8em, spacing: 0.9em, justify: false)
  align(center, box(fill: luma(222), inset: (x: 10pt, y: 6pt), text(weight: "bold", size: 15pt, title)))
  v(1.1em)
  body
}
