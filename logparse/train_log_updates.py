"""
แพตช์สำหรับ bert_pytorch/train_log.py และ bert_pytorch/trainer/pretrain.py

ยืนยันกับโค้ดจริงในรีโป (bert_pytorch/model/log_model.py, train_log.py) แล้วว่า:
  - BERTLog.forward(x, time_info) คืน dict {"logkey_output","time_output","cls_output"}
  - result["cls_output"] = x[:, 0]  <- นี่คือ h_DIST ที่ต้องการ ไม่ใช่ full sequence
  - dataloader ให้ batch เป็น dict คีย์ "bert_input" และ "time_input"
  - hidden size อยู่ที่ bert.hidden (attribute ของ BERT class)

โค้ดที่ส่งมาก่อนหน้านี้ (h = model(batch); torch.sum(h, dim=0)) เรียกผิด
signature — forward ต้องการ (x, time_info) แยกกัน และคืน dict ไม่ใช่ tensor
รันจริงจะ error ทันที ไม่ใช่แค่ผิดเชิงตรรกะ แก้ให้ตรงกับ API จริงด้านล่าง
"""

import torch


def calculate_center(model, data_loader_list, device):
    """
    ใช้แทน BERTTrainer.calculate_center เดิม

    P7: ต้องเรียกด้วย [train_data_loader] เท่านั้น ห้ามส่ง valid_data_loader
    ปนเข้ามา (โค้ดเดิมในรีโปส่งทั้งคู่ ทำให้ valid รั่วเข้า training objective
    และเสี่ยง hypersphere collapse)
    """
    model.eval()
    outputs = None
    total_samples = 0

    with torch.no_grad():
        for data_loader in data_loader_list:
            for data in data_loader:
                data = {key: value.to(device) for key, value in data.items()}
                result = model.forward(data["bert_input"], data["time_input"])
                cls_output = result["cls_output"]  # h_DIST, shape [B, hidden]

                if outputs is None:
                    outputs = torch.zeros(cls_output.size(-1), device=device)
                outputs += torch.sum(cls_output.detach(), dim=0)
                total_samples += cls_output.size(0)

    model.train()
    if total_samples == 0:
        raise RuntimeError(
            "ไม่มีข้อมูลใน data_loader_list เลย — เช็คว่าไม่ได้ส่ง valid loader "
            "เข้ามาปนโดยไม่ได้ตั้งใจ (ควรมีแค่ train loader)"
        )
    return outputs / total_samples


def check_hypersphere_collapse(epoch: int, cls_outputs: torch.Tensor, std_floor: float = 1e-5) -> None:
    """
    เรียกทุก epoch หลังได้ cls_output (h_DIST) ของ batch/epoch นั้นมาแล้ว
    ถ้า std ลู่เข้า 0 = โมเดลโกงด้วยการ output ค่าคงที่แทนการเรียนจริง
    (Deep SVDD ต้นทางเตือนเรื่องนี้ไว้ตรง ๆ แต่เปเปอร์ LogBERT ไม่พูดถึงเลย)

    std_floor = 1e-5 เป็นค่าตั้งต้นที่ยังไม่ผ่านการจูน ควรเก็บ std ของ epoch
    แรก ๆ ไว้เป็น baseline แล้วเทียบเป็นสัดส่วนแทนการเทียบค่าคงที่ตรง ๆ
    เพราะ scale ของ hidden layer ต่างกันได้ตาม hidden size ที่ตั้ง
    """
    std_dist = torch.std(cls_outputs).item()
    print(f"[epoch {epoch}] hypersphere std = {std_dist:.6f}")
    if std_dist < std_floor:
        raise RuntimeError(
            f"Hypersphere collapse ที่ epoch {epoch} (std={std_dist:.2e}) "
            f"— โมเดล output ค่าเกือบคงที่ หยุดเทรนเพื่อตรวจสอบก่อนไปต่อ"
        )
