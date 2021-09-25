import os
import random

import numpy as np
from PIL import Image
from numpy import asarray
import pandas as pd
import torch
from skimage import transform
from torch.utils.data import Dataset
import torchvision.transforms as transforms
import torchvision.transforms.functional as functional


class Resize:
    """Resize the image in a sample to a given size.

    Args:
        output_size (tuple or int): Desired output size. If tuple, output is
            matched to output_size. If int, smaller of image edges is matched
            to output_size keeping aspect ratio the same.
    """

    def __init__(self, output_size):
        assert isinstance(output_size, (int, tuple))
        self.output_size = output_size

    def __call__(self, sample):
        new_h, new_w = self.output_size
        new_h, new_w = int(new_h), int(new_w)
        sample['image'] = transform.resize(sample['image'], (new_h, new_w), preserve_range=True).astype('uint8')

        return sample


class CenterCrop:
    def __init__(self, output_size):
        self.output_size = output_size

    def __call__(self, sample):
        sample['image'] = functional.center_crop(sample['image'], self.output_size)
        return sample


class RandomHorizontalFlip:
    def __init__(self, probability=0.5):
        self.probability = probability
        self.flip = transforms.RandomHorizontalFlip(p=probability)

    def __call__(self, sample):
        sample['image'] = self.flip(sample['image'])
        return sample


class RandomVerticalFlip:
    def __init__(self, probability=0.5):
        self.probability = probability
        self.flip = transforms.RandomVerticalFlip(p=probability)

    def __call__(self, sample):
        sample['image'] = self.flip(sample['image'])
        return sample


class ToTensor:
    """Convert ndarrays in sample to Tensors."""

    def __call__(self, sample):
        # swap color axis because
        # numpy image: H x W x C
        # torch image: C X H X W
        image = sample['image'].transpose((2, 0, 1))
        return {'image': torch.from_numpy(image),
                'mass': torch.from_numpy(sample['mass']),
                'calories': torch.from_numpy(sample['calories'])}


class Normalize:
    """Normalize values."""

    def __init__(self, image_means, image_stds, mass_max=1.0, calories_max=1.0):
        self.means = image_means
        self.stds = image_stds
        self.mass_max = mass_max
        self.calories_max = calories_max

    def __call__(self, sample):
        sample['mass'] = sample['mass'] / self.mass_max
        sample['calories'] = sample['calories'] / self.calories_max
        sample['image'] = functional.normalize(sample['image'], self.means, self.stds)
        return sample


def create_nutrition_df(root_dir):
    csv_files = [os.path.join(root_dir, 'metadata', 'dish_metadata_cafe1.csv'),
                 os.path.join(root_dir, 'metadata', 'dish_metadata_cafe2.csv')]
    dish_metadata = {'dish_id': [], 'mass': [], 'calories': []}
    for csv_file in csv_files:
        with open(csv_file, "r") as f:
            for line in f.readlines():
                parts = line.split(',')

                # Temporary hack before i can fix the data extraction
                dish_id = parts[0]
                frames_path = os.path.join(root_dir, 'imagery', 'side_angles',
                                           dish_id,
                                           'camera_A')
                frame = os.path.join(frames_path, '1.jpg')
                if not os.path.exists(frame):
                    continue

                dish_metadata['dish_id'].append(parts[0])
                dish_metadata['calories'].append(int(float(parts[1])))
                dish_metadata['mass'].append(parts[2])

    return pd.DataFrame.from_dict(dish_metadata)


def split_dataframe(dataframe: pd.DataFrame, split):
    index = list(dataframe.index.copy())
    samples = len(index)
    random.shuffle(index)
    train_end = int(samples * split['train'])
    val_end = train_end + int(samples * split['validation'])
    train_index = index[:train_end]
    val_index = index[train_end:val_end]
    test_index = index[val_end:]
    return dataframe.loc[train_index], dataframe.loc[val_index], dataframe.loc[test_index]


class Nutrition5kDataset(Dataset):
    def __init__(self, dish_calories, root_dir, transform=None):
        self.dish_calories = dish_calories
        self.root_dir = root_dir
        self.transform = transform

    def __len__(self):
        return len(self.dish_calories)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()

        frames_path = os.path.join(self.root_dir, 'imagery', 'side_angles', self.dish_calories.iloc[idx]['dish_id'],
                                   'camera_A')
        frame = os.path.join(frames_path, '1.jpg')

        image = Image.open(frame)
        image = asarray(image)

        mass = self.dish_calories.iloc[idx]['mass']
        mass = np.array([mass])
        mass = mass.astype('float').reshape(1, 1)
        calories = self.dish_calories.iloc[idx]['calories']
        calories = np.array([calories])
        calories = calories.astype('float').reshape(1, 1)
        sample = {'image': image, 'mass': mass, 'calories': calories}

        if self.transform:
            sample = self.transform(sample)

        return sample
