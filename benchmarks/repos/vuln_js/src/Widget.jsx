import React from "react";
import DOMPurify from "dompurify";

export function Bio({ html }) {
  // GT:react_dangerously|xss|CWE-79|yes
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}

export function BioSafe({ html }) {
  // SAFE:safe_dompurify_dangerously|xss
  return <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
}

export function showMessage(msg) {
  const el = document.getElementById("msg");
  // GT:innerhtml|xss|CWE-79|yes
  el.innerHTML = msg;
}

export function showMessageSafe(msg) {
  const el = document.getElementById("msg");
  // SAFE:safe_textcontent|xss
  el.textContent = msg;
}

export function Hello({ name }) {
  return <p>Hello {name}</p>;
}
