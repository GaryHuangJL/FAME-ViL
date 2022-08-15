# Copyright (c) Facebook, Inc. and its affiliates.

from typing import Dict

from mmf.models.composition import NormalizationLayer
from mmf.modules.losses import (
    BatchBasedClassificationLoss,
    ContrastiveLoss,
    CrossEntropyLoss,
)
from torch import Tensor, nn

from .base import FashionCLIPBaseModel


class FashionCLIPForMTL(FashionCLIPBaseModel):
    def __init__(self, config):
        super().__init__(config.clip_config, config.get("adapter_config", None))
        self.tasks = config.tasks
        self.heads = nn.ModuleDict()
        self.loss_funcs = nn.ModuleDict()
        self.config = config

        self.init_heads()
        self.init_losses()

    def init_heads(self):
        if "itc" in self.tasks:
            self.heads["itc"] = NormalizationLayer()
        if "tgir" in self.tasks:
            self.heads["tgir"] = NormalizationLayer()
        if "scr" in self.tasks:
            self.heads["scr"] = nn.Linear(
                self.clip.config.projection_dim, self.config.num_labels
            )

    def init_losses(self):
        if "itc" in self.tasks:
            self.loss_funcs["itc"] = ContrastiveLoss()
        if "tgir" in self.tasks:
            self.loss_funcs["tgir"] = BatchBasedClassificationLoss()
        if "scr" in self.tasks:
            self.loss_funcs["scr"] = CrossEntropyLoss()

    def flatten_for_clip(self, sample_list: Dict[str, Tensor]) -> Dict[str, Tensor]:
        to_be_flattened = ["input_ids", "attention_mask"]
        to_be_flattened_dim = []
        flattened = self.flatten(sample_list, to_be_flattened, to_be_flattened_dim)
        return flattened

    def _forward_itc(self, sample_list: Dict[str, Tensor]) -> Dict[str, Tensor]:
        visual_embeddings = self.clip.get_image_features(
            sample_list.image, task_name="itc"
        )
        visual_embeddings = self.heads["itc"](visual_embeddings)

        text_embeddings = self.clip.get_text_features(
            sample_list.input_ids, sample_list.attention_mask, task_name="itc"
        )
        text_embeddings = self.heads["itc"](text_embeddings)

        output_dict = {
            "scores": visual_embeddings,
            "targets": text_embeddings,
        }

        loss = {}
        loss["itc_loss"] = self.loss_funcs["itc"](sample_list, output_dict)
        output_dict["losses"] = loss

        return output_dict

    def _forward_tgir(self, sample_list: Dict[str, Tensor]) -> Dict[str, Tensor]:
        tar_embeddings = self.clip.get_image_features(
            sample_list.tar_image, task_name="tgir"
        )
        tar_embeddings = self.heads["tgir"](tar_embeddings)

        ref_embeddings = self.clip.get_image_features(
            sample_list.ref_image, task_name="tgir"
        )
        text_embeddings = self.clip.get_text_features(
            sample_list.input_ids, sample_list.attention_mask, task_name="tgir"
        )
        comp_embeddings = ref_embeddings + text_embeddings  # vector addition
        comp_embeddings = self.heads["tgir"](comp_embeddings)

        output_dict = {
            "comp_feats": comp_embeddings,
            "tar_feats": tar_embeddings,
        }

        loss = {}
        loss["tgir_loss"] = self.loss_funcs["tgir"](sample_list, output_dict)
        output_dict["losses"] = loss

        return output_dict

    def _forward_scr(self, sample_list: Dict[str, Tensor]) -> Dict[str, Tensor]:
        visual_embeddings = self.clip.get_image_features(
            sample_list.image, task_name="scr"
        )
        text_embeddings = self.clip.get_text_features(
            sample_list.input_ids, sample_list.attention_mask, task_name="scr"
        )
        comp_embeddings = visual_embeddings + text_embeddings  # vector addition
        comp_embeddings = self.heads["scr"](comp_embeddings)

        output_dict = {
            "scores": comp_embeddings,
        }

        loss = {}
        loss["scr_loss"] = self.loss_funcs["scr"](sample_list, output_dict)
        output_dict["losses"] = loss

        return output_dict

    def _forward(self, sample_list: Dict[str, Tensor]) -> Dict[str, Tensor]:
        if sample_list.dataset_name == "fashiongen":
            return self._forward_itc(sample_list)
        if sample_list.dataset_name == "fashioniq":
            return self._forward_tgir(sample_list)
        if sample_list.dataset_name == "fashiongen_cls":
            return self._forward_scr(sample_list)

    def check_dim(self, sample_list: Dict[str, Tensor]) -> Dict[str, Tensor]:
        self._check_dim(sample_list, "image", 4)
        self._check_dim(sample_list, "image_id", 1)
        self._check_dim(sample_list, "input_ids", 2)
        self._check_dim(sample_list, "attention_mask", 2)
        self._check_dim(sample_list, "targets", 1)
        return sample_list