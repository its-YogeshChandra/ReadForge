import UploadForm from '@/components/upload/UploadForm';

export const metadata = {
  title: 'Upload Document | ReadForge',
  description: 'Upload PDF documents for processing and analysis.',
};

export default function UploadPage() {
  return (
    <main className="min-h-screen bg-[--color-bg-warm] py-12 px-4 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="max-w-3xl mx-auto mb-8">
        <h1 className="text-3xl font-light text-[--color-charcoal]">
          Document Upload
        </h1>
        <p className="text-sm text-[--color-muted-grey] mt-1">
          Upload your PDF documents for processing
        </p>
      </div>

      {/* Upload Form */}
      <UploadForm />
    </main>
  );
}
