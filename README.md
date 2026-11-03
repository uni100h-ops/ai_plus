# AI+

Created by **Antonio Fernández García**, an independent software developer, for the **Meta Global AI Developer Hackathon**.

[https://metaquant-forge.onrender.com/login](https://metaquant-forge.onrender.com/login)

**Demo password:** Provided in the project submission

This is a private research prototype developed especially for the competition, building on my earlier GPU optimization work.

<details>
<summary><strong>What is AI+?</strong></summary>

**Enhancements for Meta AI models**

AI+ combines Meta AI models with Simulated Bifurcation running on NVIDIA GPUs through Modal to improve response times and solution quality in complex tasks.

For image generation and editing, AI+ uses Muse Spark 1.3 to clarify the user's request before sending it to Muse Image. The goal is to produce images that follow the original instructions more closely. Both AI and AI+ use the same image model and settings, allowing a direct comparison of output quality and execution time.

</details>

<details>
<summary><strong>How to test AI+?</strong></summary>

1. Open the demo: https://metaquant-forge.onrender.com/login
2. Enter the password provided in the project submission.
3. Select a model.

   <img width="404" height="177" alt="image" src="https://github.com/user-attachments/assets/8c35c75f-c64e-4fd0-8193-1afffa499703" />

4. Try a practical complex spreadsheet example. Click “View data” to inspect the CSV file.
   
<img width="374" height="269" alt="image" src="https://github.com/user-attachments/assets/c0c27862-b7a5-4f43-8e87-f755906e3d3b" />

6. Review the task in the “Question or problem” section.

<img width="430" height="500" alt="image" src="https://github.com/user-attachments/assets/fff171fb-7868-4303-9366-4685e19eb607" />

7. Click “Interpret request”.

<img width="183" height="225" alt="image" src="https://github.com/user-attachments/assets/cdff1186-9890-465e-b367-d77c2cf5609c" />

8. Click “Run” to start AI and AI+ simultaneously. Each result appears as soon as that path finishes.

<img width="314" height="54" alt="image" src="https://github.com/user-attachments/assets/9441d1a5-a953-4b97-ae2d-49e10c5c0ebb" />

9. Click “Explain Results with AI” to analyze and compare the AI and AI+ results.

<img width="534" height="320" alt="image" src="https://github.com/user-attachments/assets/cadf31f1-beed-49dc-ba01-f82ae9ace067" />

10. Click “Download csv solution” below each result to download its CSV file.

<img width="743" height="234" alt="image" src="https://github.com/user-attachments/assets/15ce8fae-c50c-4c38-bb56-4daffa6f31bc" />

</details>

<details>
<summary><strong>Tests Results</strong></summary>

[Download Tests_results_images.zip](Tests_results_images.zip?raw=true)

| **Model** | **Test case** | **AI time** | **AI+ time** | **Faster AI** | **Better AI solution** | **Solution quality** | **Failures** |
|---|---|---:|---:|---|---|---|---|
| Muse Spark Open · Fireworks | Test 1. Complex Real Sample | 70.04 s | 24.61 s | **AI+** | **AI+** | AI+ lower reported cost:<br>€1,149.37 vs €1,162.23. | None |
| Muse Spark Open · Fireworks | Test 2. Radio Channels | 120.37 s* | 12.62 s | **—** | **AI+** | AI+: valid solution, objective 257.<br>AI: no result. | AI |
| Muse Spark Open · Fireworks | Test 3. Balance Tasks | 106.81 s | 19.03 s | **AI+** | **AI+** | AI+ better objective:<br>264.281 vs 331.281. | None |
| Muse Spark Open · Fireworks | Test 4. Select Projects | 85.64 s | 10.73 s | **AI+** | **AI / AI+** | Same objective:<br>−265. | None |
| Muse Spark Open · Fireworks | Test 5. Advanced QUBO | 43.17 s | 12.60 s | **AI+** | **AI+** | AI+ better objective:<br>−282 vs −244. | None |
| Muse Spark 1.3 | Test 6. Complex Real Sample | 33.76 s | 8.04 s | **AI+** | **AI / AI+** | Same reported cost:<br>€1,149.37. | None |
| Muse Spark 1.3 | Test 7. Radio Channels | 48.45 s* | 3.49 s | **—** | **AI+** | AI+: valid solution, objective 257.<br>AI: incomplete answer. | AI |
| Muse Spark 1.3 | Test 8. Balance Tasks | 54.53 s* | 3.12 s | **—** | **AI+** | AI+: valid solution, objective 264.281.<br>AI: incomplete answer. | AI |
| Muse Spark 1.3 | Test 9. Select Projects | 41.41 s | 2.49 s | **AI+** | **AI / AI+** | Same objective:<br>−265. | None |
| Muse Spark 1.3 | Test 10. Advanced QUBO | 43.63 s | 4.16 s | **AI+** | **AI+** | AI+ better objective:<br>−282 vs −258. | None |
| Muse Wonder | Test 11. Complex Real Sample | 24.98 s | 4.65 s | **AI+** | **AI / AI+** | Same reported cost:<br>€1,149.37. | None |
| Muse Wonder | Test 12. Radio Channels | 45.81 s* | 4.02 s | **—** | **AI+** | AI+: valid solution, objective 257.<br>AI: incomplete answer. | AI |
| Muse Wonder | Test 13. Balance Tasks | 43.46 s | 3.80 s | **AI+** | **AI+** | AI+ better objective:<br>264.281 vs 275.781. | None |
| Muse Wonder | Test 14. Select Projects | 28.60 s | 2.73 s | **AI+** | **AI / AI+** | Same objective:<br>−265. | None |
| Muse Wonder | Test 15. Advanced QUBO | 43.19 s | 2.70 s | **AI+** | **AI+** | AI+ better objective:<br>−282 vs −268. | None |
| Muse Image | Test 16. Generate image | 28.58 s | 14.36 s | **AI+** | **AI+** | AI: slower, with an unrequested human-like hand.<br>AI+: faster, without that visible defect. | None |

</details>

<details>
<summary><strong>What the comparison demonstrates</strong></summary>

The website displays per-path elapsed time, reported model usage, output tables or images, and available verification evidence. **Data and verification** shows the recorded details.

- Numerical comparisons use the same selected Meta model and input. AI+ has an additional tool, so this is not an equal-compute experiment.
- Path times include model calls and any optimizer startup, computation and validation. The shared interpretation step and optional results explanation are separate.
- Constraint and arithmetic checks validate the encoded numerical problem. They do not establish that a natural-language request was interpreted perfectly. General model-generated spreadsheet calculations are not independently recalculated.
- Image quality is assessed against the request; it is not automatically scored. A faster response alone does not establish better quality, and either path can fail.

The results table reflects one recorded comparison per case. Times marked with an asterisk measure time until failure. “AI / AI+” indicates a tie in the reported result; “—” indicates no speed comparison because AI failed. “Failures” refers to execution failures; visual defects are described under “Solution quality”. Numerical results are taken from the screenshots, without independent verification of the underlying CSV/JSON outputs. The screenshots have been updated for the AI+ branding; measured values and generated result images are unchanged.

The primary fit is **Build for Your World**: turn a familiar business spreadsheet and plain-language instructions into an actionable assignment, with a downloadable result and evidence the user can inspect. The research question also connects to **Push the Frontier**: when does combining a Meta model with a numerical GPU tool improve a decision-making workflow?

The implementation combines a browser interface, a Python/FastAPI gateway on Render, Meta model integrations, structured table validation, independently executed comparison paths, and a Modal GPU worker using PyTorch and Simulated Bifurcation. It is a working research prototype with fictional demonstration data; production adoption and real customer impact remain to be established.

Existing licensing and component attribution are retained in [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).

</details>

<sub>AI+ is an independent, non-commercial research prototype created by Antonio Fernández García for the Meta Global AI Developer Hackathon. It uses Meta models but is not an official Meta product and is not endorsed by Meta. The demo has restricted access and is intended for research and evaluation.</sub>
