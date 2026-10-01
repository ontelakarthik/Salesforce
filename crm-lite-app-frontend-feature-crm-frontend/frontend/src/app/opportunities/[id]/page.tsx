import Opportunity from "@/components/clm/pages/Opportunity";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Opportunity id={id} />;
}
