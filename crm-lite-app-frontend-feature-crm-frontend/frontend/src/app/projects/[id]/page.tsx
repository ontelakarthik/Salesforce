import Project from "@/components/clm/pages/Project";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Project id={id} />;
}
