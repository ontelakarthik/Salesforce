import CadenceTemplateDetail from "@/components/clm/pages/CadenceTemplateDetail";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CadenceTemplateDetail id={id} />;
}
