export default function Home() {
  // GT:next_public_secret_code|secret-exposed-to-browser|CWE-200|yes
  const key = process.env.NEXT_PUBLIC_API_SECRET;
  return <main>Home {key ? "ok" : ""}</main>;
}
