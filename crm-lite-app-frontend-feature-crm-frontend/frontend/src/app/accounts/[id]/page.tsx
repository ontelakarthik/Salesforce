import Account from "@/components/clm/pages/Account";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Account id={id} />;
}
