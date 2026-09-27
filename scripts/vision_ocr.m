#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <PDFKit/PDFKit.h>
#import <Vision/Vision.h>

static NSError *OCRError(NSString *message) {
    return [NSError errorWithDomain:@"vision-ocr"
                               code:1
                           userInfo:@{NSLocalizedDescriptionKey: message}];
}

static CGImageRef CreatePageImage(PDFPage *page, CGFloat scale, NSError **error) {
    NSRect bounds = [page boundsForBox:kPDFDisplayBoxMediaBox];
    size_t width = (size_t)ceil(NSWidth(bounds) * scale);
    size_t height = (size_t)ceil(NSHeight(bounds) * scale);
    if (width == 0 || height == 0) {
        *error = OCRError(@"PDF page has invalid dimensions");
        return NULL;
    }

    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(
        NULL, width, height, 8, 0, colorSpace,
        (CGBitmapInfo)kCGImageAlphaPremultipliedLast
    );
    CGColorSpaceRelease(colorSpace);
    if (!context) {
        *error = OCRError(@"Could not create the PDF page bitmap");
        return NULL;
    }

    CGContextSetRGBFillColor(context, 1, 1, 1, 1);
    CGContextFillRect(context, CGRectMake(0, 0, width, height));
    CGContextScaleCTM(context, scale, scale);
    CGContextTranslateCTM(context, -NSMinX(bounds), -NSMinY(bounds));
    [page drawWithBox:kPDFDisplayBoxMediaBox toContext:context];

    CGImageRef image = CGBitmapContextCreateImage(context);
    CGContextRelease(context);
    if (!image) *error = OCRError(@"Could not render the PDF page");
    return image;
}

static NSString *RecognizeImage(CGImageRef image, NSError **error) {
    VNRecognizeTextRequest *request = [VNRecognizeTextRequest new];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.usesLanguageCorrection = YES;
    request.automaticallyDetectsLanguage = YES;

    VNImageRequestHandler *handler =
        [[VNImageRequestHandler alloc] initWithCGImage:image options:@{}];
    if (![handler performRequests:@[request] error:error]) return nil;

    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    for (VNRecognizedTextObservation *observation in request.results) {
        VNRecognizedText *candidate = [observation topCandidates:1].firstObject;
        if (candidate) [lines addObject:candidate.string];
    }
    return [lines componentsJoinedByString:@"\n"];
}

static NSDictionary *OCRPDF(NSData *data, NSString *file, CGFloat scale, NSError **error) {
    PDFDocument *document = [[PDFDocument alloc] initWithData:data];
    if (!document) {
        *error = OCRError(@"The input is not a valid PDF");
        return nil;
    }

    NSMutableArray *pages = [NSMutableArray arrayWithCapacity:document.pageCount];
    for (NSInteger index = 0; index < document.pageCount; index++) {
        PDFPage *page = [document pageAtIndex:index];
        if (!page) {
            *error = OCRError([NSString stringWithFormat:@"Missing PDF page %ld", index + 1]);
            return nil;
        }

        CGImageRef image = CreatePageImage(page, scale, error);
        if (!image) return nil;
        NSString *text = RecognizeImage(image, error);
        CGImageRelease(image);
        if (!text) return nil;
        [pages addObject:@{@"page": @(index + 1), @"text": text}];
    }
    return @{@"file": file, @"pages": pages};
}

static BOOL SelfTest(NSError **error) {
    NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(600, 200)];
    [image lockFocus];
    [[NSColor whiteColor] setFill];
    NSRectFill(NSMakeRect(0, 0, 600, 200));
    [@"ReadForge Vision OCR" drawAtPoint:NSMakePoint(40, 80)
                           withAttributes:@{
                               NSFontAttributeName: [NSFont systemFontOfSize:42],
                               NSForegroundColorAttributeName: NSColor.blackColor
                           }];
    [image unlockFocus];

    PDFPage *page = [[PDFPage alloc] initWithImage:image];
    PDFDocument *document = [PDFDocument new];
    [document insertPage:page atIndex:0];
    NSDictionary *result = OCRPDF(document.dataRepresentation, @"self-test.pdf", 2, error);
    NSString *text = [result[@"pages"] firstObject][@"text"];
    return [text containsString:@"ReadForge Vision OCR"];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSError *error = nil;
        if (argc == 2 && strcmp(argv[1], "--self-test") == 0) {
            if (SelfTest(&error)) {
                puts("Vision OCR self-test passed");
                return 0;
            }
            if (!error) error = OCRError(@"Vision did not recognize the test text");
        } else if (argc == 2 || argc == 3) {
            NSString *path = [NSString stringWithUTF8String:argv[1]];
            CGFloat scale = argc == 3 ? atof(argv[2]) : 2;
            if (scale <= 0) {
                error = OCRError(@"render-scale must be greater than zero");
            } else {
                // Deliberately load the complete PDF into memory before PDFKit parses it.
                NSData *data = [NSData dataWithContentsOfFile:path options:0 error:&error];
                NSDictionary *result = data ? OCRPDF(data, path, scale, &error) : nil;
                NSData *json = result
                    ? [NSJSONSerialization dataWithJSONObject:result
                                                       options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys
                                                         error:&error]
                    : nil;
                if (json) {
                    fwrite(json.bytes, 1, json.length, stdout);
                    putchar('\n');
                    return 0;
                }
            }
        } else {
            error = OCRError(@"Usage: vision-ocr PDF [render-scale]");
        }

        fprintf(stderr, "vision-ocr: %s\n", error.localizedDescription.UTF8String);
        return 1;
    }
}
