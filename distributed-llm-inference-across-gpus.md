# Distributed LLM inference across GPUs

### User

Is there a repo that is about inferencing an LLM accross distributed GPUs via API. For instance, I will rent many services with limited GPUs but I then have each of them calculates each weights seperately which is the multi headed attention layer. Do you get the idea?

---

### Assistant

<details>
<summary>Thinking</summary>





</details>

Yes, the idea exists and has several implementations. But one correction first, because it decides which repo you want.

**Splitting attention heads across nodes is tensor parallelism.** That needs an all-reduce after every attention block and every MLP block, so roughly 2 syncs per layer, 60+ round trips per token for a 30-layer model. Over rented boxes talking through HTTP/internet, that dies. Benchmarks show cross-node tensor parallel on 2.5 GbE drops to about 1.8 tok/s versus 14.2 tok/s for the same setup inside one box, and that is on a LAN, not the open internet.

**What actually works is pipeline parallelism**: node A holds layers 0-9, node B holds 10-19, and so on. One activation tensor gets passed at each boundary, so only a handful of hops per token.

Repos that do it:

- **Petals** (bigscience-workshop/petals) - the closest to your description. Each participant loads a portion of the model's layers on their own GPU and joins a network serving the rest, reaching around 6 tok/s for Llama 2 70B single-batch. Caveat: GitHub activity has been limited recently and it is PyTorch + hivemind, so no GGUF.
- **llama.cpp RPC backend** (`rpc-server`) - the most practical today. Simple, stable, works with quantized models.
- **exo** (exo-explore/exo) - heterogeneous devices, layer-aware pipeline.
- **distributed-llama** (b4rtaz) - tensor parallel, but assumes fast Ethernet, not rented cloud.
- **vLLM with Ray** - supports `pipeline_parallel_size` across nodes, the production-grade option if your rented instances sit in the same region/VPC.

Practical advice for your rental scenario: rent all nodes in the **same provider and same region** so you get sub-millisecond private networking, then use vLLM pipeline parallel or llama.cpp RPC. If the nodes are on different providers, the network cost usually exceeds what you save on GPUs.

---

### User

เพราะฉันอยากใช้โมเดลตัวใหญ่ขึ้นแต่ไม่มีเงินมากพอ แต่จะอาศัยโควต้าฟรีของ service ต่างเพื่อช่วยกันคำนวณแต่ละ layers

---

### Assistant

<details>
<summary>Thinking</summary>





</details>

เข้าใจเป้าหมายครับ แต่ต้องบอกตรงๆ ว่าเส้นทางนี้แทบไม่เวิร์คในทางปฏิบัติ ด้วยเหตุผล 3 ข้อ

**1. Free tier ส่วนใหญ่รับ inbound ไม่ได้** node ใน pipeline ต้องเปิดพอร์ตให้ node อื่นยิงเข้ามา แต่ Colab/Kaggle ไม่มี public IP และ ToS ห้ามใช้เป็น server/proxy ต้องพึ่ง tunnel ซึ่งเพิ่ม latency อีกชั้น

**2. Session ตายกลางทาง** Colab ตัดเมื่อ idle และมีเพดานเวลา พอ node ใดตาย pipeline พังทั้งสาย ต้อง reroute ใหม่ทุกครั้ง

**3. ช้าจนใช้งานไม่ได้** Petals บน public swarm วัดได้ราว 0.9 tok/s และ TTFT เกิน 12 วินาที ช้ากว่าโมเดลเล็กที่รันบนเครื่องตัวเองเสียอีก

**ทางที่ตอบโจทย์เดียวกันแต่ได้ผลจริง: ใช้ free API tier ที่เขาแจกโมเดลใหญ่อยู่แล้ว**

เขารันโมเดล 100B+ บนฮาร์ดแวร์ตัวเองให้ฟรี ไม่ต้องมาแบ่ง layer เอง

- **Groq** gpt-oss-120b ฟรี 30 req/min, 1,000 req/วัน เพดานจริงคือ 200K tokens/วัน
- **Cerebras** ราว 1M tokens/วัน ได้ gpt-oss-120b และ gemma-4-31b
- **Gemini Flash** ฟรีทั้งตระกูล context ถึง 1M แต่ข้อแลกเปลี่ยนคือ Google ระบุว่าเนื้อหา free tier ถูกนำไปพัฒนาผลิตภัณฑ์
- **OpenRouter** โมเดล `:free` 20 RPM, 50 req/วัน ขยับเป็น 1,000/วัน ถ้าเคยเติมเครดิต 10 ดอลลาร์

ถ้าจะทำแบบรวมโควต้าหลายเจ้าเข้าด้วยกัน มีไลบรารีชื่อ **freelm** ที่ pool free tier ของ OpenRouter, Gemini, NVIDIA NIM, Groq, Cerebras, Mistral ไว้หลัง OpenAI-compatible API ตัวเดียว หมุน key อัตโนมัติและ failover ข้ามเจ้าเมื่อโดน 429 ซึ่งคือสิ่งที่คุณอยากได้จริงๆ คือ "ยืมโควต้าหลายเจ้ามารวมกัน" แค่ทำที่ระดับ request ไม่ใช่ระดับ layer

ข้อควรระวัง: free tier พวกนี้เปลี่ยนบ่อยมาก GitHub Models ปิดไปแล้วเมื่อ 30 ก.ค. 2026 อย่าสร้างอะไรที่เป็น load-bearing บนมัน

ส่วนเครื่องโน้ตบุ๊ก VRAM 4-6 GB ของคุณ ยังเหมาะกับโมเดล 7-8B quantized Q4 ไว้ใช้ตอน offline หรืองานที่ข้อมูลอ่อนไหวออกเน็ตไม่ได้ แล้วสลับไป API ฟรีตอนต้องการโมเดลใหญ่

---

### User

แต่ฉันต้องการรันโมเดลอย่างปลอดภัย เพราะอย่างน้อยผู้ให้บริการ GPU ก็ไม่ได้เก็บ Log ข้อความอยู่แล้ว และมีตั้งหลายเจ้านอกจาก Colab กับ Kaggle Hostinger ล่ะ อะไรอื่นๆอีก เผลอๆแค่สร้างหลาย account ก็มีโควต้าให้อันละ 4GB VRAM ทำสัก 6 อันก็ 24GB VRAM แล้ว

---

### Assistant

<details>
<summary>Thinking</summary>





</details>

มีจุดที่ต้องแย้งตรงๆ ก่อนครับ เพราะมันกระทบเป้าหมายหลักของคุณเลย

**การแบ่ง layer ข้ามผู้ให้บริการ ทำให้ privacy แย่ลง ไม่ใช่ดีขึ้น**

node แรกในสายต้องถือ embedding layer ซึ่งแปลว่ามันเห็น token ID ของ prompt คุณตรงๆ เป็นข้อความอ่านได้เลย ส่วน node ถัดไปได้ activation tensor ซึ่งมีงานวิจัย embedding inversion ที่กู้ข้อความต้นฉบับกลับมาได้ในระดับที่น่ากังวล เดิมคุณต้องเชื่อใจผู้ให้บริการ 1 เจ้า พอทำแบบนี้กลายเป็นต้องเชื่อใจ 6 เจ้าพร้อมกัน และถ้าเจ้าใดเจ้าหนึ่งถือ layer แรกไว้ เกมจบทันที ตัว Petals เองก็ไม่ได้เคลมเรื่อง privacy ไว้เลย

อีกอย่าง free tier มักมีสิทธิ์ในข้อมูลมากกว่า paid tier เช่น Gemini ระบุชัดว่าเนื้อหาฝั่ง free tier ถูกนำไปพัฒนาผลิตภัณฑ์ แต่ paid tier ไม่ ดังนั้นสมมติฐานที่ว่า "อย่างน้อยเขาก็ไม่เก็บ log" ใช้ไม่ได้กับของฟรี

**เรื่องหลาย account**

ผิด ToS ของทุกเจ้าที่ยกมา และเขาตรวจกันจริง Lightning AI ต้อง phone verify, Colab ผูกกับ Google account ที่คุณใช้ Drive กับ Gmail ทำงานอยู่ ความเสี่ยงคือโดนแบน account หลัก ผมไม่ช่วยวางแผนส่วนนี้ครับ

**และคณิตศาสตร์ก็ไม่ออกด้วย**

6 x 4GB ไม่ได้เท่ากับ 24GB ใช้งานจริง CUDA context กับ PyTorch overhead กินราว 1 GB ต่อ node ก่อนโหลด weight แล้วยังต้องเผื่อ KV cache และ activation buffer อีก เหลือใช้จริงอาจราว 12-15GB

ที่สำคัญกว่านั้น ตัวเลข 4GB มาจากไหนครับ ของฟรีที่มีจริงตอนนี้คือ **Kaggle Notebooks ให้ T4 หรือ P100 16GB VRAM ฟรี 30 ชม./สัปดาห์** ใน session เดียว account เดียว ถูกกติกา และ Kaggle ยังมีออปชัน 2x T4 ในบาง config ด้วย นั่นคือ 32GB ใน account เดียว มากกว่าที่คุณจะได้จากการไปหมุน 6 account เสียอีก

**สองทางที่ตอบโจทย์ "ปลอดภัย" ได้จริง**

1. **รันบนโน้ตบุ๊กตัวเองด้วยโมเดล MoE** ด้วย RAM 24-32GB ของคุณ ลอง Qwen3-30B-A3B quantize Q4 บน llama.cpp แล้วใช้ `-ot "exps=CPU"` เก็บ expert ไว้ใน RAM ส่วน attention อยู่บน GPU 4-6GB เพราะ MoE activate แค่ราว 3B params ต่อ token มันจึงวิ่งได้ ไม่ใช่ dense 30B ที่คลานเป็นเต่า อันนี้ privacy 100% ไม่มี hop ออกเน็ตเลย ตรงกับที่คุณต้องการที่สุด

2. **เช่า GPU เป็นชั่วโมงตอนใช้จริง** Vast.ai เริ่มราว $0.07/hr, RunPod ราว $0.17/hr ใช้วันละ 2 ชม. ตกเดือนละไม่กี่ร้อยบาท instance เป็นของคุณคนเดียว ควบคุมได้เต็ม และง่ายกว่าบริหาร 6 node ที่หลุดกลางทางตลอดเวลามาก

ถ้าสนใจข้อ 1 บอกได้ครับ จะช่วยหาคำสั่ง llama.cpp กับโมเดลที่เหมาะกับสเปกเครื่องคุณ

---

### User

คือสุดท้ายคุณก็ยังแนะนำให้เสียเงินเหรอ หลักๆฉันอยากรันโมเดลที่ใหญ่กว่านี้ แบบฟรี และเร็วขึ้นอีก ฉลาดขึ้นอีก

---

### Assistant

ถูกครับ ผมแนะนำเสียเงินเพราะคุณตั้งเงื่อนไขว่าต้อง**ปลอดภัย**ด้วย และ ฟรี + ใหญ่ + เร็ว + ปลอดภัย พร้อมกันทั้งสี่ข้อ มันไม่มีอยู่จริง ต้องทิ้งอย่างน้อยหนึ่งข้อ

แต่ถ้าคุณยอมทิ้งข้อ "ปลอดภัย" สำหรับงานบางประเภท ของฟรีที่ดีมากมีอยู่ และดีกว่าแผนแบ่ง layer ของคุณคนละโลก

**ฟรี + ใหญ่ + เร็ว (ไม่ต้องเสียเงินสักบาท)**

- **Cerebras** ฟรีราว 1M tokens/วัน ได้ gpt-oss-120b ความเร็วระดับหลายร้อย token/วินาที
- **Groq** ฟรี 30 req/นาที เพดานจริงคือ 200K tokens/วัน ได้ gpt-oss-120b เช่นกัน
- **Gemini Flash** ฟรี context ถึง 1M tokens
- **OpenRouter** โมเดล `:free` 50 req/วัน ขยับเป็น 1,000/วัน ถ้าเคยเติมเครดิต 10 ดอลลาร์ครั้งเดียว

ต่อ 4 อันนี้เข้าด้วยกันผ่าน **freelm** (pool free tier หลายเจ้าไว้หลัง OpenAI-compatible API ตัวเดียว หมุน key และ failover เองเมื่อโดน 429) คุณจะได้ระดับล้าน token ต่อวัน จากโมเดล 120B ที่เร็วกว่าอะไรที่คุณจะรันเองได้ ทุกอย่างถูกกติกา ใช้ account ของตัวเองเจ้าละหนึ่งอัน

เทียบกับแผนเดิม: 6 node ที่ได้ราว 0.9 tok/s รันโมเดลที่เล็กกว่า และหลุดทุกชั่วโมง

**แล้วงานที่ปลอดภัยจริงๆ ล่ะ**

แยกตามประเภทงาน ไม่ต้องหาคำตอบเดียวที่ตอบทุกอย่าง

- งานทั่วไป เช่น เขียนโค้ด ถามเรื่อง finetuning เรียนรู้ concept → ยิง Groq/Cerebras ไปเลย ข้อมูลพวกนี้ไม่ได้ sensitive
- งานที่ข้อมูลออกเน็ตไม่ได้ เช่น log จริง ข้อมูลลูกค้า → รันเองบนเครื่อง โมเดลเล็กลงหน่อย แต่ 100% ปลอดภัย

ถ้าอยากได้ของฟรีที่รันเองแล้ว VRAM เยอะๆ **Kaggle Notebooks ให้ T4 หรือ P100 16GB ฟรี 30 ชม./สัปดาห์** โหลด weight ของคุณเองขึ้นไปรันได้ นี่คือ 16GB ฟรีจาก account เดียว ถูกกติกา ไม่ต้องแบ่ง layer ให้ปวดหัว

คุณอยากให้ผมช่วยเซ็ตตัวไหนก่อน ตัวรวม free API หรือตัวรันบนเครื่อง

---

### User

งั้นตัดเรื่องปลอดภัยก่อน อยากรันโมเดลเก่งๆ เช่น Qwen, Deepseek แบบฟรี เพราะ openrouter downtime บ่อยมาก

---

### Assistant

<details>
<summary>Thinking</summary>





</details>

OpenRouter free tier ไม่เสถียรเพราะมัน route ไปหา provider ปลายทางที่โดน rate limit อยู่แล้วอีกที ตัวที่ควรย้ายไปคือเจ้าที่โฮสต์เองโดยตรง

**ตัวหลัก: NVIDIA NIM**

น่าจะตรงกับคุณที่สุด มีโมเดล DeepSeek หลายตัว และไม่มีเพดาน token รายวัน ครอบคลุมกว่า 120 โมเดล open-weight ทั้ง DeepSeek, Kimi, GLM, Qwen, MiniMax, Llama, Mistral, gpt-oss และตระกูล Nemotron ของ NVIDIA เอง ระดับ 40 RPM ต่อโมเดล ไม่ต้องใช้บัตรเครดิต แค่ยืนยันเบอร์โทร รุ่นบนสุดตอนนี้มี deepseek-v4-flash context 1.3M กับ qwen3.5-397b-a17b

Endpoint คือ `https://integrate.api.nvidia.com/v1` เป็น OpenAI-compatible เปลี่ยน base URL กับ key จากโค้ดเดิมได้เลย

**สำรองอีกชั้น**

- **ModelScope** แพลตฟอร์มจีน โมเดลฟรีกว่า 50 ตัว ทั้ง Qwen, DeepSeek, GLM ไม่ต้องใช้บัตร ต้นทางเดียวกับ Qwen เลย
- **OVHcloud AI Endpoints** 14 โมเดลฟรี โฮสต์ใน EU มี Qwen, Mistral, Llama, DeepSeek, gpt-oss-120B ที่ 12 RPM และมี anonymous tier ที่ไม่ต้องสมัครด้วยซ้ำ
- **Z.ai** 4 โมเดลฟรีตระกูล GLM ไม่ต้องใช้บัตร GLM-4.6 เก่งเรื่องโค้ดมาก
- **SiliconFlow** latency ต่ำสุดถ้ายิงจากเอเชีย
- **Ollama Cloud** มี deepseek-v4-pro context 1M

**Trial credit ที่คุ้ม** Alibaba Cloud Model Studio ให้ 1M tokens ต่อโมเดล 90 วัน สำหรับ Qwen โดยตรง, Scaleway 1M tokens แบบถาวร, SambaNova $5 สามเดือน

**ส่วนเรื่อง downtime ให้แก้ด้วย failover ไม่ใช่หา provider ที่สมบูรณ์แบบ**

ของฟรีทุกเจ้าล่มทั้งนั้น วิธีที่ถูกคือเอาหลาย key มาต่อกันแล้วให้มันสลับเอง ใช้ freelm ที่บอกไปก่อนหน้า หรือ LiteLLM ที่ตั้ง `fallbacks` เป็น list ได้ ลำดับที่ผมจะวางคือ NVIDIA NIM เป็นตัวหลัก แล้ว fallback ไป Cerebras, Groq, ModelScope, Z.ai ตามลำดับ

เตือนไว้อย่างหนึ่ง Chutes.ai ปิด free tier ไปแล้วเหลือแต่แบบจ่ายเงิน และ GitHub Models ก็ปิดไปเมื่อ ก.ค. 2026 รายชื่อพวกนี้เปลี่ยนทุกไม่กี่เดือน อย่าผูก config ไว้กับเจ้าเดียว

อยากให้ผมเขียน config LiteLLM แบบ fallback chain ให้เลยไหมครับ

---

### User

Nvidia NIM คืออะไร ทำไมถึง Unlimited

---

### Assistant

<details>
<summary>Thinking</summary>





</details>

**NIM ย่อมาจาก NVIDIA Inference Microservices**

มันคือคอนเทนเนอร์สำเร็จรูปที่ห่อโมเดล + inference engine ที่ optimize แล้ว (TensorRT-LLM/vLLM) เอาไว้ด้วยกัน แล้วเปิดออกมาเป็น OpenAI-compatible API ปรัชญาคือ deploy ที่ไหนก็ได้ที่มี GPU NVIDIA โดยไม่ต้องมานั่งจูน engine เอง

ส่วน **build.nvidia.com** คือแคตตาล็อกที่ NVIDIA เอา NIM พวกนี้มารันให้ฟรีบนฮาร์ดแวร์ตัวเอง (DGX Cloud) เพื่อให้คนลองก่อน

**ทำไมถึงดูเหมือน unlimited**

เดิมเป็นระบบเครดิต 1,000 credits ต่อ account (ขอเพิ่มได้ถึง 5,000 ถ้าใช้อีเมลองค์กร) แต่ฟอรัมนักพัฒนาของ NVIDIA เองระบุว่าเลิกใช้ระบบเครดิตแล้ว เปลี่ยนมาคุมด้วย rate limit รายโมเดลแทน ซึ่ง NVIDIA ไม่ประกาศตัวเลขออกมาเป็นทางการ ที่ชุมชนรายงานกันคือราว 40 RPM ต่อโมเดล และขอเพิ่มเป็น 200 RPM ได้

ดังนั้นคำว่า unlimited หมายถึง "ไม่มีเพดาน token" ไม่ใช่ "ยิงได้ไม่อั้น" คุณยังติดกำแพง 40 req/นาทีอยู่ดี

**เหตุผลทางธุรกิจ**

NVIDIA ไม่ได้ขาย token เขาขายการ์ดจอ ค่า inference ที่แจกฟรีคืองบการตลาด เส้นทางที่เขาวางไว้คือ prototype ฟรีบน NIM แล้วค่อยไป deploy จริงด้วย NVIDIA AI Enterprise license ราว $4,500 ต่อ GPU ต่อปี เทียบกับ OpenRouter ที่ต้องจ่ายค่า compute จริงทุก token แล้วขาดทุนกับ free tier ของตัวเอง NVIDIA เลยใจกว้างกว่าได้มาก เหตุผลเดียวกับที่ Groq และ Cerebras แจกฟรี คือโชว์ชิปตัวเอง

**ข้อที่คุณต้องระวังจริงๆ**

NVIDIA นิยาม production use ไว้กว้างมาก คือการใช้ NIM เพื่ออะไรก็ตามที่ไม่ใช่การพัฒนา ทดสอบ วิจัย หรือประเมินผล รวมถึงกิจกรรมใดก็ตามที่ให้บริการผู้ใช้จริง และ production ต้องมี AI Enterprise license

แปลว่าเอาไว้เขียนโค้ด เรียนรู้ ทดลองส่วนตัว ได้สบาย แต่ถ้าจะเอาไปเป็น backend ของงานลูกค้าที่คุณรับทำ อันนั้นอยู่นอกขอบเขต free tier แล้ว (แหล่งข้อมูลบางเจ้าบอกว่า commercial use ได้ ขัดกับที่ NVIDIA เขียนเอง ผมแนะนำให้อ่าน ToS ในคอนโซลตอนสมัครด้วยตัวเองอีกรอบ)

สำหรับงานลูกค้า Groq กับ Cerebras อนุญาต commercial use บน free tier ชัดเจนกว่า

---

### User

งั้นก็ใช้ NIM เลยแล้วก็ fallback เป็น Groq และ Cerebras แค่ 3 อันพอ

---

### Assistant

แผนนี้ใช้ได้ครับ แต่มีกับดักหนึ่งที่ต้องรู้ก่อน: **context window ไม่เท่ากัน**

NIM deepseek-v4-flash รับได้ถึง 1.3M, Groq 128K, ส่วน Cerebras มีเพดาน context ราว 8K เท่านั้น แปลว่าถ้า prompt คุณยาว พอ NIM ล่มแล้ว fallback ลงไปถึง Cerebras มันจะพังซ้ำ ไม่ใช่ช่วยกู้ ดังนั้นควรแยกเป็นสองเชน

ผมเขียน config ให้แล้ว

วิธีใช้: รัน `litellm --config litellm-config.yaml --port 4000` แล้วชี้ทุกอย่าง (n8n, local AI coder, สคริปต์ Python) มาที่ `http://localhost:4000/v1` ด้วย key อะไรก็ได้ จากนั้นเรียก `big-brain` เป็นชื่อโมเดล มันจะสลับ provider ให้เองเมื่อเจอ 429 หรือ 5xx

จุดที่ควรปรับเอง

- ถ้าเป็นงานลูกค้า ให้สลับลำดับเป็น `groq-oss` เป็นตัวหลักแทน เพราะเงื่อนไข production use ของ NIM ที่คุยกันไปเมื่อกี้
- `context_window_fallbacks` คือตัวที่แก้ปัญหา context สั้นของ Cerebras พอ prompt ยาวเกิน มันจะเด้งขึ้นไปหาตัวที่รับไหวแทนที่จะ error ทิ้ง
- ตัวเลข RPM ของ Cerebras ที่แต่ละแหล่งรายงานไม่ตรงกัน บางเจ้าว่า 30 บางเจ้าว่า 5 ผมใส่ 30 ไว้ ถ้าเจอ 429 บ่อยให้ลดลง
- ชื่อโมเดลเปลี่ยนบ่อยมาก ถ้าเจอ 404 ตอนเริ่ม ให้เปิดแคตตาล็อกของแต่ละเจ้าเช็คก่อน อย่าเพิ่งโทษ config

---

### User

คือว่าฉันกำลังจะใช้ HarnessRouter อยู่แล้วดังนั้นเลยไม่จำเป็นต้องใช้ Litellm

---

### Assistant

<details>
<summary>Thinking</summary>





</details>

ตรงนี้ผมว่ามีความเข้าใจคลาดกันนิดหนึ่งครับ สองตัวนี้อยู่คนละชั้น ไม่ได้แทนกัน

**HarnessRouter route ข้าม harness ไม่ใช่ข้าม model provider**

นิยามที่เขาใช้เองคือ LLM คืนมาเป็น token ส่วน harness คือ sandbox + tools + loop ที่ทำให้ได้ไฟล์จริงออกมา GPT-5.2 กับ Claude Opus 4.8 คือ LLM ส่วน Codex กับ Claude Code คือ harness

HarnessRouter คือชั้นแปลง spec ที่นั่งอยู่ระหว่าง application ของคุณกับ harness พวกนั้น แปลง unified interface ไปเป็น API format ของแต่ละ harness โดยตัว harness เองยังคุยกับโมเดลของมันเองตามเดิม

**ที่สำคัญ: fallback ยังไม่มีในตัว**

ผู้พัฒนาเขาตอบไว้เองบน HN ว่า smart routing สำหรับ harness fallback และ cost optimization ยังอยู่ใน roadmap ดังนั้นสิ่งที่คุณต้องการ คือ NIM โดน 429 แล้วสลับไป Groq อัตโนมัติ HarnessRouter ยังทำให้ไม่ได้ตอนนี้

**สองตัวนี้ต่อกันได้ ไม่ต้องเลือก**

ตอนติดตั้ง HarnessRouter มันจะให้คุณใส่ credential ของ model provider ในหน้า Integrations ตรงนั้นแหละครับ ใส่ `http://localhost:4000/v1` ของ LiteLLM เข้าไปแทนที่จะใส่ key ของ NIM ตรงๆ แล้วคุณจะได้ทั้งสองอย่าง

```
app → HarnessRouter (เลือก harness) → LiteLLM (failover provider) → NIM / Groq / Cerebras
```

แต่มีคำถามกลับครับ harness อย่าง Codex หรือ Claude Code ผูกกับ subscription แบบเสียเงินอยู่แล้ว ซึ่งสวนทางกับโจทย์ "ฟรี" ที่คุยกันมาทั้งหมด

คุณกำลังจะเอา HarnessRouter ไปทำอะไรครับ ถ้าเป็นงาน agent ที่ต้องแก้ไฟล์จริงในโปรเจกต์ มันคนละงานกับที่เราคุยกันเรื่อง API ฟรี แต่ถ้าแค่อยากได้ endpoint เดียวยิงโมเดลหลายเจ้า LiteLLM พอแล้วจริงๆ ไม่ต้องมี HarnessRouter

---

### User

ฉัน download Litellm มาจาก github แล้ว ต้องเรียกใช้ยังไง เพราะต้องการให้โค้ดอยู่ในระบบที่จัดเตรียมไว้และปรับแต่งได้ เพราะบน github เขาระบุว่าใช้ uv add

---

### Assistant

มีจุดต้องแยกก่อนครับ `uv add litellm` กับการ clone repo มาเป็นคนละเรื่องกัน

`uv add` คือการเพิ่ม LiteLLM เป็น dependency ในโปรเจกต์**ของคุณ** ส่วนที่คุณ clone มาคือ source code ของ LiteLLM เอง สองอันนี้ใช้ในสถานการณ์ต่างกัน

**แบบ A: โค้ดอยู่ในโปรเจกต์คุณ แต่ไม่แก้ internals (แนะนำ)**

```bash
uv init llm-gateway
cd llm-gateway
uv add "litellm[proxy]"
# วาง litellm-config.yaml ไว้ในโฟลเดอร์นี้
uv run litellm --config litellm-config.yaml --port 4000
```

ได้ `pyproject.toml` + `uv.lock` ที่ commit เข้า git ได้ เวอร์ชันถูกล็อก reproduce ได้ทุกเครื่อง

**แบบ B: รันจาก source ที่ clone มา (แก้ internals ได้)**

```bash
cd litellm
uv sync --all-extras
uv run litellm --config /path/to/litellm-config.yaml --port 4000
```

หรือถ้าอยากให้โปรเจกต์คุณอ้างถึง source ที่แก้ไว้

```bash
cd llm-gateway
uv add --editable /path/to/litellm
```

แบบ editable นี้คือที่คุณน่าจะอยากได้ เพราะแก้ไฟล์ใน `/path/to/litellm` แล้วมีผลทันทีโดยไม่ต้อง reinstall

**แต่ก่อนจะไปแบบ B ลองถามตัวเองก่อนว่าจะแก้อะไร**

สิ่งที่คนมักคิดว่าต้อง fork แต่จริงๆ ทำผ่าน config ได้เลย

```python
# custom_callbacks.py
from litellm.integrations.custom_logger import CustomLogger

class MyHandler(CustomLogger):
    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        # log ลง DB, mask PII, นับ token ต่อ client
        return response

proxy_handler_instance = MyHandler()
```

```yaml
litellm_settings:
  callbacks: custom_callbacks.proxy_handler_instance
```

hook แบบนี้ครอบคลุม logging, rate limit เอง, แก้ request/response, custom auth ได้เกือบหมด โดยไม่ต้องแตะ source ซึ่งแปลว่าคุณ `uv lock --upgrade-package litellm` ตามอัปสตรีมได้เรื่อยๆ ไม่ต้องมานั่ง merge conflict ทุกรอบ

ข้อควรระวังสำหรับแบบ B: repo มีหน้า admin UI ที่เป็น Next.js แยกอยู่ใน `ui/` ตัว package จาก PyPI ชิป build สำเร็จรูปมาให้ แต่รันจาก source อาจต้อง build เองก่อน `/ui` ถึงจะขึ้น ถ้าคุณใช้แค่ API ไม่ต้องสน

จะแก้ส่วนไหนของ LiteLLM ครับ ถ้าบอกได้ผมช่วยดูว่าทำผ่าน hook ได้ไหมก่อนที่จะต้อง fork จริง

---

### User

ฉันโหลดเป็น zipfile มาเลยแหละ

---

### Assistant

ใช้ได้ครับ แต่มีสองข้อควรรู้ก่อน

zip ของ GitHub ไม่มี `.git` ติดมา แปลว่าคุณจะ `git pull` อัปเดตไม่ได้ ต้องโหลด zip ใหม่แล้วเอาไฟล์ที่แก้ไว้มา merge เองทุกครั้ง ถ้าตั้งใจจะปรับแต่งระยะยาว `git clone` คุ้มกว่ามาก แต่ถ้าแค่อยากลองก่อน zip ก็พอ

**ขั้นตอน**

```bash
unzip litellm-main.zip
cd litellm-main
ls pyproject.toml    # ต้องมีไฟล์นี้ ถ้าไม่มีแปลว่าแตกผิดชั้น
```

จากนั้นเช็คก่อนว่ามันใช้ build system แบบไหน เพราะคำสั่งที่ใช้ต่างกัน

```bash
head -20 pyproject.toml
```

- ถ้าขึ้นต้นด้วย `[project]` → `uv sync --all-extras` ใช้ได้เลย
- ถ้าขึ้นต้นด้วย `[tool.poetry]` → `uv sync` จะฟ้องว่าไม่เจอ project table ให้ใช้แทน:

```bash
uv venv
uv pip install -e ".[proxy]"
```

แล้วรัน

```bash
uv run litellm --config litellm-config.yaml --port 4000
```

**กับดักที่เจอบ่อย**

โฟลเดอร์ที่แตกออกมาจะชื่อ `litellm-main` และข้างในมีโฟลเดอร์ `litellm/` อีกชั้นซึ่งคือตัว package จริง ถ้าคุณ `cd` เข้าไปผิดชั้นแล้วสั่ง install จะเจอ error งงๆ ให้ยืนอยู่ชั้นที่มี `pyproject.toml` เสมอ

อีกอย่าง อย่ารัน `python` interactive จากในโฟลเดอร์นั้นแล้ว `import litellm` เพราะมันจะหยิบ source ในโฟลเดอร์แทน package ที่ติดตั้งไว้ ทำให้ debug สับสน

**ข้อเสนอที่ผมคิดว่าดีกว่า**

แยกเป็นสองโฟลเดอร์ คือ source ที่คุณแก้ กับโปรเจกต์ที่คุณใช้งานจริง

```bash
cd ~/projects
uv init llm-gateway
cd llm-gateway
uv add --editable ~/Downloads/litellm-main
```

แบบนี้ config, callback, และโค้ดของคุณอยู่ใน `llm-gateway` ที่ commit git ได้สะอาด ส่วน LiteLLM ที่แก้แล้วอยู่แยก วันไหนอยากกลับไปใช้เวอร์ชันทางการก็แค่ `uv remove litellm && uv add "litellm[proxy]"` จบ ไม่ต้องรื้อ

ถ้าติดตรงไหนวางข้อความ error มาได้เลยครับ

---

### User

ฉันสมัคร NIM เรียบร้อยแล้ว ฉันสามารถ upload model จาก huggingface ขึ้นไป deploy ได้ไหม

---

### Assistant

ได้ครับ แต่ไม่ใช่บน build.nvidia.com ที่คุณเพิ่งสมัคร ตรงนี้คือจุดที่คนสับสนกันบ่อย

**build.nvidia.com เป็นแคตตาล็อกอย่างเดียว อัปโหลดไม่ได้**

มันคือ NIM ที่ NVIDIA เลือกมาแล้วรันบนฮาร์ดแวร์เขา ไม่มีช่องให้เอาโมเดลของคุณขึ้นไป

**สิ่งที่ทำได้คือ self-host NIM container บน GPU ของคุณเอง**

NIM รับน้ำหนักโมเดล 3 รูปแบบ คือ Hugging Face checkpoint (.safetensors หรือ .gguf), TensorRT-LLM checkpoint และ TensorRT-LLM engine ที่ build ไว้แล้ว ตัว container จะอ่าน config เพื่อระบุ architecture และตรวจ quantization format ให้เอง

โหลดตรงจาก HF ได้เลยด้วยซ้ำ

```bash
docker run -it --rm --gpus all \
  -p 8000:8000 \
  -e HF_TOKEN=$HF_TOKEN \
  -e NIM_MODEL_NAME="hf://Qwen/Qwen2.5-0.5B" \
  nvcr.io/nim/nvidia/llm-nim:latest
```

ถ้าเป็นโมเดลที่คุณ fine-tune เองและเก็บไว้ในเครื่อง ใช้ `NIM_FT_MODEL` ชี้ไปที่โฟลเดอร์ HF checkpoint แทน แล้ว NIM จะ build TensorRT-LLM engine ให้อัตโนมัติ

```bash
docker run -it --rm --gpus all \
  -e NIM_FT_MODEL=/path/to/my-model \
  -e NIM_SERVED_MODEL_NAME="qwen-cyber-th" \
  -e NIM_CUSTOM_MODEL_NAME=custom_1 \
  -v /path/to/my-model:/path/to/my-model \
  -u $(id -u) \
  $NIM_IMAGE
```

`NIM_CUSTOM_MODEL_NAME` คือตัว cache engine ที่ build แล้ว ไม่งั้นรอบหน้าต้อง build ใหม่ทุกครั้งซึ่งกินเวลานาน

มีข้อควรระวังหนึ่ง: สำหรับ fine-tuned model ตัว PyTorch TRT-LLM backend ที่เป็นค่าเริ่มต้นรองรับไม่ได้ ต้องเปิด legacy backend ด้วย `NIM_USE_TRTLLM_LEGACY_BACKEND=1` และ `NIM_DISABLE_TRTLLM_PYTORCH_RT=1`

**แต่จุดที่คุณต้องคิดก่อนคือฮาร์ดแวร์**

self-host ต้องมี GPU NVIDIA ของตัวเอง บวกพื้นที่ดิสก์อย่างน้อย 200GB สำหรับ model cache เพราะ Llama 3.1 70B กินราว 140GB ที่ FP16 หรือราว 70GB แบบ quantized

โน้ตบุ๊ก 4-6GB VRAM ของคุณรัน NIM container ไม่ไหวครับ ถ้าจะทำจริงต้องเช่า GPU cloud ซึ่งวนกลับมาที่เรื่องค่าใช้จ่ายอีกรอบ

**ถ้าแค่อยากปรับพฤติกรรมโมเดล ไม่ต้อง deploy ใหม่ก็ได้**

NVIDIA ระบุเองว่าถ้า fine-tune โมเดลที่ NIM รองรับอยู่แล้วด้วยวิธีที่รองรับ คุณไม่ต้อง package เป็น NIM ใหม่เลย เพราะ NIM รองรับ LoRA PEFT adapter ที่เทรนด้วย NeMo framework หรือ Hugging Face Transformers ได้โดยตรง

อันนี้น่าจะตรงกับงาน finetuning ในกรอบ cybersecurity ที่คุณสนใจมากกว่า เทรน LoRA adapter ตัวเล็กๆ แล้วเสียบเข้า base model ที่มีอยู่ ถูกกว่าและเร็วกว่าการ deploy โมเดลเต็มตัวเยอะ

คุณมีโมเดลตัวไหนในใจอยู่แล้วหรือยังครับ ถ้าบอกขนาดกับ use case มาผมช่วยดูว่าต้อง GPU ระดับไหน

---

### User

แล้วไม่เสียตังเหรอ

---

### Assistant

ใช่ครับ เสียตัง ผมควรพูดให้ชัดกว่านี้ตั้งแต่แรก

**แยกให้ชัดสองเรื่อง**

1. **ใช้โมเดลที่คนอื่นโฮสต์ไว้** → ฟรีได้จริง เพราะ NVIDIA/Groq/Cerebras โหลดโมเดลตัวเดียวแล้วแชร์ให้คนหมื่นคนใช้ ต้นทุนต่อหัวจึงถูกจนแจกได้
2. **โฮสต์โมเดลของคุณเอง** → ไม่มีทางฟรี เพราะ VRAM ก้อนนั้นถูกจองไว้ให้คุณคนเดียว ไม่มีใครแชร์ต้นทุนด้วย ใครสักคนต้องจ่ายค่าการ์ด

ตัว NIM container เองโหลดฟรีสำหรับ dev/test แต่คุณต้องมี GPU ไปเสียบมันอยู่ดี และถ้าเอาไป production ก็ต้องมี AI Enterprise license ราว $4,500/GPU/ปี

**ของฟรีที่ใกล้เคียงที่สุดสำหรับโฮสต์โมเดลตัวเอง**

- **Modal** ให้เครดิตฟรีราว $5-30 ต่อเดือน แบบเติมใหม่ทุกเดือน คิดตามเวลา compute จริง เป็น serverless คือไม่มีคนเรียกก็ไม่เสียเครดิต อันนี้ใกล้เคียง "ฟรีถาวร" ที่สุดสำหรับ custom model
- **HuggingFace Spaces ZeroGPU** ฟรี แต่ได้แค่ 5 นาที/วันบน free account และจำกัดเฉพาะ Gradio + PyTorch เหมาะทำ demo ไม่เหมาะเป็น backend
- **Kaggle** T4 16GB ฟรี 30 ชม./สัปดาห์ รันโมเดลของคุณได้ แต่เปิดเป็น API ให้ข้างนอกเรียกไม่ได้ เหมาะกับทดลองและ batch job

**คำแนะนำตรงๆ**

ถ้าเป้าหมายคือ "โมเดลเก่งๆ ใช้ฟรี" → อยู่กับแผน NIM + Groq + Cerebras ที่วางไว้ จบ ไม่ต้องไปยุ่งกับ deploy เอง

ถ้าเป้าหมายคือ "อยาก finetune โมเดลให้เก่งเรื่อง cybersecurity โดยเฉพาะ" → นั่นคนละโจทย์ และเส้นทางฟรีคือ เทรน LoRA บน Kaggle (ฟรี) แล้วเอา adapter ที่ได้มารันบนโน้ตบุ๊กตัวเองด้วย llama.cpp หรือ Ollama กับ base model 7-8B quantized (ฟรี) ไม่ต้องมี NIM ไม่ต้องมี GPU cloud เลย

สองเส้นทางนี้ตอบคนละคำถาม คุณกำลังอยากได้อันไหนกันแน่ครับ

---

### User

งั้นก็ใช้ NIM catalog เหมือนเดิมละกันต้อง setup ยังไงเพื่อ inference

---

### Assistant

เร็วมากครับ NIM เป็น OpenAI-compatible ทั้งหมด

**1. เอา API key**

ไปที่ `build.nvidia.com/settings/api-keys` กด generate จะได้ key ขึ้นต้นด้วย `nvapi-`

```bash
export NVIDIA_API_KEY=nvapi-xxxxx
```

**2. เทสก่อนว่าทะลุ**

```bash
curl https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-ai/deepseek-v4-flash-0731",
    "messages": [{"role":"user","content":"สวัสดี ตอบสั้นๆ"}],
    "max_tokens": 100
  }'
```

ถ้าได้ 404 แปลว่าชื่อโมเดลไม่ตรง ให้เปิดหน้าโมเดลบน build.nvidia.com แล้วกดแท็บที่เขาโชว์โค้ดตัวอย่าง คัดลอก model string มาตรงๆ อย่าพิมพ์เอง

**3. เรียกจาก Python**

```python
from openai import OpenAI
import os

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NVIDIA_API_KEY"],
)

resp = client.chat.completions.create(
    model="deepseek-ai/deepseek-v4-flash-0731",
    messages=[{"role": "user", "content": "อธิบาย SQL injection สั้นๆ"}],
    temperature=0.6,
    max_tokens=1024,
    stream=True,
)

for chunk in resp:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

**4. ต่อเข้า LiteLLM ที่วางไว้แล้ว**

config ที่ผมทำให้เตรียมไว้ให้แล้ว แค่ตั้ง env ทั้งสามตัวแล้วรัน

```bash
export NVIDIA_API_KEY=nvapi-xxxxx
export GROQ_API_KEY=gsk_xxxxx
export CEREBRAS_API_KEY=csk-xxxxx
uv run litellm --config litellm-config.yaml --port 4000
```

จากนั้นทุกอย่างชี้มาที่ `http://localhost:4000/v1` แล้วเรียกชื่อ `big-brain` ไม่ต้องรู้ว่าเบื้องหลังเป็นเจ้าไหน

**สิ่งที่ควรรู้ตอนใช้จริง**

- โมเดลตระกูล reasoning อย่าง DeepSeek R1 จะพ่น `<think>` ออกมาด้วย ถ้าไม่อยากได้ต้อง strip เอง หรือเลือกรุ่น instruct แทน
- `stream=True` ช่วยมากเวลาชน 40 RPM เพราะคุณเห็นว่ามันเริ่มตอบหรือค้างตั้งแต่วินาทีแรก
- latency จากไทยไป NIM ค่อนข้างแกว่ง ถ้างานไหนต้องการเร็วคงที่ ให้ยิง Groq ตรงๆ แทน

ลองรันข้อ 2 ก่อนครับ ถ้าเจอ error อะไรวางมาได้เลย

---

### User

อ้าว ไม่ใช่ NGC เหรอ

---

### Assistant

คำถามดีครับ ตรงนี้ NVIDIA ทำสับสนเอง

**สองระบบที่แยกหน้าที่กัน**

| | ใช้ทำอะไร | ปลายทาง |
|---|---|---|
| key จาก build.nvidia.com (`nvapi-`) | เรียก API ที่ NVIDIA โฮสต์ให้ | `integrate.api.nvidia.com` |
| NGC API key (ngc.nvidia.com) | ดึง container มา self-host | `nvcr.io` registry |

ที่คุณจะทำคือแบบแรก ยิง API ไปหาโมเดลในแคตตาล็อก ดังนั้นใช้ key จาก build.nvidia.com

NGC จะจำเป็นก็ต่อเมื่อคุณจะ `docker pull nvcr.io/nim/...` มารันบน GPU ตัวเอง ซึ่งเราตัดทิ้งไปแล้วเพราะเครื่องไม่ไหว

**แต่มันทับซ้อนกันจริง**

account บน build.nvidia.com อยู่ใต้ NVIDIA Developer Program ซึ่งเป็นระบบเดียวกับ NGC และ key ที่ออกจาก build ก็มักใช้ login เข้า `nvcr.io` ได้ด้วย (ใช้ username เป็น `$oauthtoken` แล้วเอา key เป็น password) NVIDIA ควบรวมสองอันนี้มาเรื่อยๆ ช่วงหลัง ผมเลยไม่การันตีว่าตอนนี้แยกกันชัดแค่ไหน

วิธีเช็คที่เร็วที่สุดคือรัน curl ที่ผมให้ไป ถ้าได้ 200 ก็จบ ไม่ต้องไปยุ่งกับ NGC เลย ถ้าได้ 401 ค่อยไปสร้าง key ใหม่จากหน้า `build.nvidia.com/settings/api-keys` โดยตรง

ลองเลยครับ แล้วบอกว่าได้อะไรกลับมา

---

### User

มีอายุแค่ 6 เดือน

---

### Assistant

ปกติครับ NVIDIA ตั้ง default ให้ key หมดอายุ ไม่ได้แปลว่า account หรือ quota คุณหมดอายุด้วย

ตอนสร้าง key หน้านั้นมักมีช่องให้เลือกอายุอยู่ ลองดูว่าเลือกได้ยาวกว่านี้หรือเลือก never expire ได้ไหม บาง key type เขาบังคับเพดานไว้ ถ้าเลือกไม่ได้ก็แค่สร้างใหม่ตอนใกล้ครบ ใช้เวลาไม่ถึงนาที

**สิ่งที่ควรทำตั้งแต่ตอนนี้**

อย่าฝัง key ลงโค้ดตรงๆ ให้อ่านจาก env อย่างเดียว วันที่ต้องเปลี่ยนคุณจะแก้ที่เดียวจบ

```bash
# .env  (ใส่ใน .gitignore ด้วย)
NVIDIA_API_KEY=nvapi-xxxxx   # หมดอายุ 2027-03
GROQ_API_KEY=gsk_xxxxx
CEREBRAS_API_KEY=csk-xxxxx
```

จดวันหมดอายุไว้ในคอมเมนต์แบบนี้ แล้วตั้งเตือนในปฏิทินล่วงหน้าสักสองสัปดาห์ เพราะอาการตอน key หมดอายุคือ 401 เฉยๆ ไม่มีคำเตือนล่วงหน้า ถ้าลืมแล้วมางมทีหลังจะเสียเวลา

ข้อดีอย่างหนึ่งของ LiteLLM ที่วางไว้คือถ้า NIM เด้ง 401 มันจะ fallback ไป Groq ให้อัตโนมัติ ระบบไม่ล่ม คุณมีเวลาไปสร้าง key ใหม่แบบไม่ต้องรีบ แต่ก็ควรเช็ค log เป็นระยะ ไม่งั้นจะไม่รู้เลยว่าตัวหลักตายไปแล้ว

ทีนี้ลองรัน curl ดูหรือยังครับ ผ่านไหม

---

### User

ได้แล้ว never expires พอดีมัน edit ได้ แล้วยังไงต่อนะ

---

### Assistant

ดีครับ งั้นเหลือแค่ยิงเทส

```bash
export NVIDIA_API_KEY=nvapi-xxxxx

curl https://integrate.api.nvidia.com/v1/models \
  -H "Authorization: Bearer $NVIDIA_API_KEY"
```

ผมให้ยิง `/models` ก่อน `/chat/completions` เพราะมันตอบสองคำถามพร้อมกัน คือ key ใช้ได้ไหม และชื่อโมเดลที่ใช้ได้จริงคืออะไรบ้าง จะได้ไม่ต้องเดาชื่อแล้วเจอ 404

ได้ list มาแล้วเลือกสักตัวมายิงจริง

```bash
curl https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<เอาชื่อจาก /models มาใส่>",
    "messages": [{"role":"user","content":"ตอบสั้นๆ ว่าทำงานได้"}],
    "max_tokens": 50
  }'
```

ผ่านแล้วค่อยไปต่อสามขั้นตามลำดับนี้

1. เอาชื่อโมเดลจริงที่ได้ ไปแก้ใน `litellm-config.yaml` แทนชื่อที่ผมเดาไว้
2. สมัคร Groq กับ Cerebras เอา key มาใส่ env ให้ครบ (สองเจ้านี้สมัครเร็วมาก ไม่ต้องใช้บัตร)
3. รัน `uv run litellm --config litellm-config.yaml --port 4000` แล้วเทสอีกรอบที่ `http://localhost:4000/v1` ด้วยชื่อ `big-brain`

วาง output ของ `/models` มาได้เลยครับ ถ้ามันยาวมากเอาแค่ 10 บรรทัดแรกพอ ผมจะช่วยเลือกตัวที่เหมาะกับงานคุณแล้วแก้ config ให้ตรง

---

### User

ฉันใช้ powershell

---

### Assistant

สำคัญครับ ใน PowerShell คำว่า `curl` เป็น alias ของ `Invoke-WebRequest` ไม่ใช่ curl จริง คำสั่งแบบ bash ที่ผมให้ไปจะพังทันที ใช้ `Invoke-RestMethod` แทนดีกว่า

**ตั้ง env var**

```powershell
$env:NVIDIA_API_KEY = "nvapi-xxxxx"
```

อันนี้อยู่แค่ใน session ปัจจุบัน ปิดหน้าต่างแล้วหาย ถ้าอยากให้ถาวร

```powershell
[Environment]::SetEnvironmentVariable("NVIDIA_API_KEY", "nvapi-xxxxx", "User")
```

แบบถาวรต้องเปิด PowerShell ใหม่ถึงจะเห็นค่า

**เช็คว่า key ใช้ได้ และดูรายชื่อโมเดล**

```powershell
$headers = @{ "Authorization" = "Bearer $env:NVIDIA_API_KEY" }

$models = Invoke-RestMethod -Uri "https://integrate.api.nvidia.com/v1/models" -Headers $headers
$models.data | Select-Object -ExpandProperty id | Select-Object -First 20
```

**ยิงจริง**

```powershell
$body = @{
    model = "<เอาชื่อจากข้างบนมาใส่>"
    messages = @(
        @{ role = "user"; content = "ตอบสั้นๆ ว่าทำงานได้" }
    )
    max_tokens = 50
} | ConvertTo-Json -Depth 5

$resp = Invoke-RestMethod -Uri "https://integrate.api.nvidia.com/v1/chat/completions" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body

$resp.choices[0].message.content
```

`-Depth 5` จำเป็นครับ เพราะ `ConvertTo-Json` ของ PowerShell ตัดความลึกที่ 2 เป็นค่าเริ่มต้น array ของ message จะกลายเป็นข้อความขยะแล้วได้ 400 กลับมา

ถ้าเจอปัญหาภาษาไทยเป็นตัวยึกยือ ให้เพิ่มบรรทัดนี้ก่อน

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

อีกอย่าง ถ้าคุณจะรัน LiteLLM ด้วย ผมแนะนำให้ทำใน WSL2 แทน Windows ตรงๆ เพราะ dependency บางตัวของ proxy ชอบมีปัญหาบน Windows native และ path ใน config จะสะอาดกว่ามาก ถ้ายังไม่มี WSL บอกได้ครับ

---

### User

model เยอะมาก เพดานเท่าไหร่นะ

---

### Assistant

ตรงนี้ตอบชัดไม่ได้ครับ เพราะ NVIDIA ไม่ประกาศตัวเลข

ที่ทราบคือระบบเครดิตเดิม (1,000 credits ต่อ account, ขอเพิ่มได้ถึง 5,000) ถูกยกเลิกไปแล้ว ฟอรัมนักพัฒนาของ NVIDIA เองระบุว่า build.nvidia.com เปลี่ยนมาคุมด้วย rate limit รายโมเดลแทน และ**ไม่เผยแพร่ตัวเลขเป็นทางการ** ตัวเลขที่ชุมชนรายงานกันคือราว 40 RPM ต่อโมเดล ขอเพิ่มเป็น 200 RPM ได้ แต่ให้ถือว่าเป็นการสังเกตของผู้ใช้ ไม่ใช่คำสัญญาจาก NVIDIA

**วิธีหาเพดานจริงของ account คุณ**

ยิงแล้วอ่าน response header เอา ตัวเลขที่เชื่อได้คือตัวที่เซิร์ฟเวอร์ตอบกลับ ไม่ใช่ตัวเลขจากบล็อกไหน

```powershell
$r = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/chat/completions" `
    -Method Post -Headers $headers -ContentType "application/json" -Body $body

$r.Headers.GetEnumerator() | Where-Object { $_.Key -match "ratelimit|retry" }
```

ใช้ `Invoke-WebRequest` ไม่ใช่ `Invoke-RestMethod` นะครับ เพราะตัวหลังทิ้ง header ไป เหลือแต่ body

ถ้ามี header ตระกูล `x-ratelimit-*` ออกมา นั่นคือคำตอบจริงของ account คุณ ถ้าไม่มีก็แปลว่า NVIDIA ไม่เปิดเผย ต้องวัดเอาจากตอนโดน 429

**ข้อสรุปเชิงปฏิบัติ**

อย่าออกแบบระบบให้พึ่งตัวเลข RPM ตัวใดตัวหนึ่ง เพราะมันเปลี่ยนได้โดยไม่แจ้ง ให้ระบบทนต่อ 429 แทน ซึ่ง config LiteLLM ที่วางไว้จัดการให้แล้วด้วย `num_retries`, `cooldown_time` และ fallback chain

ส่วนเรื่องโมเดลเยอะเกินไป คุณไม่ต้องเลือกจากทั้งร้อยตัว เลือกสัก 3 ตัวพอ

- ตัวหลักสำหรับเขียนโค้ดและงานยาก เช่น DeepSeek รุ่นล่าสุด หรือ Qwen ตัวใหญ่
- ตัวเร็วสำหรับงานง่ายซ้ำๆ เช่น Llama หรือ Nemotron ขนาดกลาง
- ตัว long context ถ้ามีงานอ่านเอกสารยาว

วาง `/models` output มาสัก 20 บรรทัดก็ได้ครับ ผมช่วยคัดให้ตรงกับงาน cybersecurity กับ finetuning ของคุณ

---

### User

PS C:\Users\Mynew> $r = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/chat/completions" `
>>     -Method Post -Headers $headers -ContentType "application/json" -Body $body

Security Warning: Script Execution Risk
Invoke-WebRequest parses the content of the web page. Script code in the web page might be run when the page is
parsed.
      RECOMMENDED ACTION:
      Use the -UseBasicParsing switch to avoid script code execution.

      Do you want to continue?

[Y] Yes  [A] Yes to All  [N] No  [L] No to All  [S] Suspend  [?] Help (default is "N"):
Invoke-WebRequest : Operation cancelled due to security concerns. Use -UseBasicParsing parameter for safe HTML parsing
without script execution.
At line:1 char:6
+ $r = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/chat ...
+      ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : SecurityError: (https://integra...hat/completions:Uri) [Invoke-WebRequest], InvalidOpera
   tionException
    + FullyQualifiedErrorId : WebCmdletIEParsingDeclined,Microsoft.PowerShell.Commands.InvokeWebRequestCommand

PS C:\Users\Mynew>
PS C:\Users\Mynew> $r.Headers.GetEnumerator() | Where-Object { $_.Key -match "ratelimit|retry" }
You cannot call a method on a null-valued expression.
At line:1 char:1
+ $r.Headers.GetEnumerator() | Where-Object { $_.Key -match "ratelimit| ...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : InvalidOperation: (:) [], RuntimeException
    + FullyQualifiedErrorId : InvokeMethodOnNull

---

### Assistant

นี่คือ Windows PowerShell 5.1 ซึ่งเรียก Internet Explorer engine มา parse HTML ตอบ ทั้งที่ API ตอบเป็น JSON เพิ่ม `-UseBasicParsing` จบเลย

error ที่สองเป็นผลพวงจากอันแรก เพราะ `$r` ว่าง คำสั่งเลยเรียก method บน null

```powershell
$r = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/chat/completions" `
    -Method Post -Headers $headers -ContentType "application/json" -Body $body `
    -UseBasicParsing

$r.Headers.GetEnumerator() | Where-Object { $_.Key -match "ratelimit|retry" }
```

อ่าน body ด้วย

```powershell
($r.Content | ConvertFrom-Json).choices[0].message.content
```

**แนะนำให้ลง PowerShell 7**

5.1 จะมีเรื่องจุกจิกแบบนี้เรื่อยๆ ทั้ง `-UseBasicParsing`, encoding UTF-8 เพี้ยน, และ `ConvertTo-Json` ที่ตัด depth ส่วน PowerShell 7 แก้ไปหมดแล้ว

```powershell
winget install Microsoft.PowerShell
```

ติดตั้งเสร็จเรียกด้วย `pwsh` แทน `powershell` ตัวเก่ายังอยู่ ไม่ทับกัน

ใน pwsh คุณจะใช้ `curl.exe` ตัวจริงได้ด้วย (ต้องใส่ `.exe` เพื่อเลี่ยง alias) ทำให้ copy คำสั่งจากเอกสารฝั่ง Linux มาใช้ได้ตรงๆ ไม่ต้องแปลงทุกครั้ง

ลองรันอันบนก่อนครับ ถ้ามี header `x-ratelimit-*` โผล่มา วางมาให้ดูได้เลย

---

### User

PS C:\Users\Mynew> $r = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/chat/completions" `
>>     -Method Post -Headers $headers -ContentType "application/json" -Body $body `
>>     -UseBasicParsing
PS C:\Users\Mynew>
PS C:\Users\Mynew> $r.Headers.GetEnumerator() | Where-Object { $_.Key -match "ratelimit|retry" }
PS C:\Users\Mynew> ($r.Content | ConvertFrom-Json).choices[0].message.content
It looks like your message came through as blank or just question marks. Could you please retype or clarify what youâd like to ask?

---

### Assistant

สองเรื่องแยกกัน แต่ข่าวดีคือระบบทำงานแล้ว

**1. ไม่มี rate limit header**

ยืนยันตามที่คุยกันไว้ว่า NVIDIA ไม่เปิดเผยตัวเลข ให้ปล่อยผ่าน ไปพึ่ง retry/fallback ของ LiteLLM แทน

**2. ภาษาไทยเพี้ยน เพราะ encoding**

โมเดลบอกว่าได้รับข้อความว่างหรือเป็นเครื่องหมายคำถาม แปลว่า **ข้อความไทยของคุณพังตอนส่งออกไป** ไม่ใช่พังตอนแสดงผล ตัว `â` ที่เห็นคือ UTF-8 ถูกอ่านเป็น Windows-1252 อีกที

สาเหตุคือ `Invoke-WebRequest` ของ 5.1 ส่ง body เป็น ASCII เมื่อคุณให้ string มาตรงๆ ทางแก้คือแปลงเป็น byte array เอง

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$body = @{
    model = "<ชื่อโมเดลของคุณ>"
    messages = @(
        @{ role = "user"; content = "ตอบสั้นๆ ว่าทำงานได้" }
    )
    max_tokens = 50
} | ConvertTo-Json -Depth 5

$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)

$r = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/chat/completions" `
    -Method Post -Headers $headers `
    -ContentType "application/json; charset=utf-8" `
    -Body $bytes -UseBasicParsing

[System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) |
    ConvertFrom-Json | ForEach-Object { $_.choices[0].message.content }
```

ต้องแปลงทั้งขาส่งและขารับ เพราะ 5.1 เดา encoding ผิดทั้งสองทาง

**แต่คุณจะเจอเรื่องนี้ทุกครั้งที่พิมพ์ภาษาไทย**

งานของคุณเป็นภาษาไทยเกือบทั้งหมด การต้องมานั่งแปลง byte array ทุกรอบมันไม่ไหว ลง PowerShell 7 เถอะครับ

```powershell
winget install Microsoft.PowerShell
```

ใน pwsh โค้ดเดิมที่ผมให้ครั้งก่อนจะทำงานได้เลย ไม่ต้องแปลง byte เพราะมัน default UTF-8 ทั้งขาเข้าขาออก

และถ้าจะรัน LiteLLM ต่อ อยู่ใน WSL2 หรือ pwsh จะราบรื่นกว่ามาก ตัว Python client (`openai` library) ก็จัดการ UTF-8 ให้เองอยู่แล้ว ไม่มีปัญหานี้ตั้งแต่ต้น

จริงๆ ถ้าเป้าหมายคือต่อ LiteLLM ข้าม PowerShell ไปเลยก็ได้ครับ เทสด้วย Python สั้นๆ แทน

---

