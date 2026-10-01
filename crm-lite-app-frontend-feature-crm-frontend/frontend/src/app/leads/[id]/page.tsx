import Lead from "@/components/clm/pages/Lead";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Lead id={id} />;
}
